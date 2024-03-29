import logging
from dataclasses import dataclass, field, asdict
from os import getenv
from typing import Any, Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from yarl import URL

logger = logging.getLogger('dsbot.assistant.cog')

DEFAULT_MODEL = "@hf/thebloke/llama-2-13b-chat-awq"


@dataclass
class UnscopedPrompt:
    prompt: str
    raw: bool = field(default=False, init=False)
    stream: bool = field(default=False, init=False)
    max_tokens: int = field(default=256, init=False)


@dataclass
class Message:
    content: str
    role: Literal["user", "system", "assistant"] = "assistant"


@dataclass
class Response:
    response: str


@app_commands.guild_only()
class Assistant(commands.Cog):
    def __init__(
            self,
            bot: discord.Client,
            cf_account_id: str,
            cf_api_token: str,
            session: aiohttp.ClientSession | None = None,
            *,
            rest_url: str | URL | None = None,
    ):
        self.bot = bot

        if session is None:
            from orjson import dumps
            self.session = aiohttp.ClientSession(
                json_serialize=lambda obj: dumps(obj).decode("utf-8", errors="ignore")
            )
        else:
            self.session = session

        self._cf_account_id = cf_account_id
        self._cf_api_token = cf_api_token

        if rest_url is None:
            self.rest_url = URL(f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/ai/run/")
        else:
            if isinstance(rest_url, URL):
                self.rest_url = rest_url
            else:
                self.rest_url = URL(rest_url)

        self.headers = {
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/json",
            "DNT": "1",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "ds-bot"
        }
        self.session.headers.update(self.headers)

        if getenv("SYSTEM_PROMPT") is None:
            self.system_message = ("You are a chatbot with the objective to help in any way necessary the user, "
                                   "while providing only true information and keeping the answers short and concise.")
        else:
            self.system_message = getenv("SYSTEM_PROMPT")

    async def _request(
            self,
            url: URL,
            method: str,
            headers: dict[str, Any] | None = None,
            payload: dict[str, Any] | None = None,
            query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Make a request using aiohttp
        :param url: the url to make the request to
        :param method: method to use
        :param headers: headers to use
        :param payload: payload to send (used for POST requests)
        :param query: query to append to the url
        :return: the response as a dict (json
        """
        async with self.session.request(
                method,
                url,
                headers=headers,
                json=payload,
                params=query
        ) as resp:
            return await resp.json()

    async def unscoped_prompt(
            self,
            prompt: str,
            raw: bool = False,
            max_tokens: int = 256,
            *, model: str = DEFAULT_MODEL
    ) -> Response:
        """
        Send an unscoped prompt to the llm
        :param prompt: the prompt to send
        :param raw: whether the prompt uses raw parameters in the prompt
        :param max_tokens: the maximum number of tokens to generate
        :param model: the model to use (list of models: https://developers.cloudflare.com/workers-ai/models/)
        :return: the response from the llm
        """
        data = {
            "prompt": prompt,
            "raw": raw,
            "stream": False,
            "max_tokens": max_tokens
        }

        url = self.rest_url / model
        response = await self._request(url, "POST", payload=data)

        return self.parse_response(response)

    async def scoped_prompt(
            self,
            messages: list[Message],
            max_tokens: int = 256,
            *, model: str = DEFAULT_MODEL
    ):
        """
        Send a scoped prompt to the llm.
        This allows to have a conversation with the llm using the previous messages as knowledge.
        :param messages: a list of messages to send
        :param max_tokens: the maximum number of tokens to generate
        :param model: the model to use (list of models: https://developers.cloudflare.com/workers-ai/models/)
        :return: the response from the llm
        """
        if messages[0].role != "system":
            messages.insert(0, Message(
                content=self.system_message,
                role="system"
            ))

        payload = {
            "messages": [asdict(message) for message in messages],
            "stream": False,
            "max_tokens": max_tokens
        }

        url = self.rest_url / model
        response = await self._request(url, "POST", payload=payload)

        return self.parse_response(response)

    async def single_scoped_prompt(self, prompt: str, max_tokens: int = 256, model: str = DEFAULT_MODEL) -> Response:
        """
        Send a single prompt with system message
        :param prompt: prompt to send
        :param max_tokens: max number of tokens to generate
        :param model: model to use
        :return: the response from the llm
        """
        messages = [Message(content=prompt, role="user")]

        return await self.scoped_prompt(messages, max_tokens, model=model)

    @staticmethod
    def parse_response(response: dict) -> Response:
        if "error" in response:
            raise commands.CommandError(response["error"])

        if response.get("success", False) is False:
            logger.error(response)
            raise commands.CommandError("An error occurred")

        return Response(**response["result"])

    @app_commands.command(name="ask", description="Ask a question to the assistant")
    @app_commands.checks.cooldown(3, 10, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(prompt="The question you want to ask", model="The model to use (use openchat by default)")
    async def unscoped_prompt_command(self, interaction: discord.Interaction, prompt: str, model: str | None = None):
        """Send a prompt to the assistant"""
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response

        if model is None:
            model = DEFAULT_MODEL

        await resp.defer(thinking=True)
        llm_response = await self.unscoped_prompt(prompt, model=model)

        return await interaction.followup.send(llm_response.response)


async def setup(bot: commands.Bot) -> None:
    logger.debug("Loading assistant cog")
    client_id = getenv("CF_ACCOUNT_ID", None)
    api_token = getenv("CF_TOKEN", None)

    if client_id is None or api_token is None:
        logger.warning("Cloudflare credentials not found, assistant cog will not be loaded")
        return

    await bot.add_cog(Assistant(bot, client_id, api_token, ))
    logger.info("Assistant cog loaded")
