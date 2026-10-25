"""LangChain side of the eval: judge output schema, chat model clients, prompt chains and pricing.

    - ChatOpenAI (langchain-openai) calls OpenAI models; ChatGoogleGenerativeAI (langchain-google-genai)
      calls Gemini models. Each model's provider is set in eval/config.yaml.
    - ChatPromptTemplate fills prompts/model_instruction.txt and prompts/judge_rubric.txt.
    - PydanticOutputParser checks the judge's JSON against the rubric's shape (six 1-5 scores).
    - Runnable.with_retry re-asks the judge when its reply does not parse.
"""

import json
import os
import sys
import urllib.request
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from . import ROOT

DIMENSIONS = ["coverage", "mece", "client_specificity", "depth_and_insight",
              "prioritisation_and_flow", "instruction_following"]


# ---------- judge output schema (matches the JSON shape in prompts/judge_rubric.txt) ----------

class DimensionScore(BaseModel):
    reasoning: str
    score: int = Field(ge=1, le=5)


class Scores(BaseModel):
    coverage: DimensionScore
    mece: DimensionScore
    client_specificity: DimensionScore
    depth_and_insight: DimensionScore
    prioritisation_and_flow: DimensionScore
    instruction_following: DimensionScore


class KeyPoint(BaseModel):
    point: str
    covered: Literal["full", "partial", "none"]


class Judgement(BaseModel):
    key_points: list[KeyPoint]
    scores: Scores
    strengths: str
    weaknesses: str


# ---------- models and chains ----------

def model_provider(cfg, model):
    for section in ("candidates", "judges"):
        for spec in cfg[section]["models"]:
            if spec["id"] == model:
                return spec["provider"]
    raise KeyError(model)


def make_llm(cfg, section, model):
    """A LangChain chat model for one model ID; both clients retry rate limits and server errors."""
    provider = model_provider(cfg, model)
    api_key = os.environ[cfg["providers"][provider]["api_key_env"]]
    timeout = cfg["api"].get("timeout_seconds", 300)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key, max_tokens=section["max_tokens"],
                          temperature=section.get("temperature"), timeout=timeout, max_retries=5)
    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, max_output_tokens=section["max_tokens"],
                                      temperature=section.get("temperature"), timeout=timeout, max_retries=6)
    sys.exit(f"Unknown provider '{provider}' for {model}; use openai or google.")


def make_prompt(path):
    return ChatPromptTemplate.from_messages([("human", (ROOT / path).read_text(encoding="utf-8"))])


def candidate_chain(prompt, llm):
    """{context, question} -> AIMessage"""
    return prompt | llm


def judge_chain(prompt, llm):
    """{context, question, golden_answer, candidate_answer} -> {"message": AIMessage, "judgement": Judgement}

    The whole chain is retried when the reply is not valid JSON in the rubric's shape.
    """
    parser = PydanticOutputParser(pydantic_object=Judgement)
    chain = prompt | llm | RunnableParallel(message=RunnablePassthrough(), judgement=parser)
    return chain.with_retry(retry_if_exception_type=(OutputParserException,), stop_after_attempt=3)


# ---------- reading replies ----------

def message_text(message):
    """Text of an AIMessage whose content is a string or a list of content blocks (e.g. Gemini 3)."""
    if isinstance(message.content, str):
        return message.content.strip()
    return "".join(b.get("text", "") for b in message.content
                   if isinstance(b, dict) and b.get("type") == "text").strip()


def load_pricing(cfg, models):
    """$ per token (input, output) for each model ID, from a public price list; free-tier providers cost 0."""
    try:
        with urllib.request.urlopen(cfg["api"]["pricing_url"], timeout=30) as response:
            listed = {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
                      for m in json.load(response)["data"]}
    except Exception:
        print("Note: could not load the price list; costs of paid models will be blank.")
        listed = {}
    pricing = {}
    for model in models:
        provider = model_provider(cfg, model)
        if cfg["providers"][provider].get("free_tier"):
            pricing[model] = (0.0, 0.0)
        elif f"{provider}/{model}" in listed:
            pricing[model] = listed[f"{provider}/{model}"]
        else:
            print(f"Note: no price found for {provider}/{model}; its cost will be blank.")
    return pricing


def usage(message, model, pricing):
    tokens = message.usage_metadata or {}
    prompt_tokens, completion_tokens = tokens.get("input_tokens"), tokens.get("output_tokens")
    cost = None
    if model in pricing and prompt_tokens is not None and completion_tokens is not None:
        cost = round(prompt_tokens * pricing[model][0] + completion_tokens * pricing[model][1], 6)
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost_usd": cost}
