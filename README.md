# Tokenria

**See where your LLM tokens actually go, and how much of what you generate is actually worth using.**

## The Problem

If you use LLMs regularly for work, you're paying for tokens without any real visibility into two things:

1. **Structural waste.** How much of your spend is repeated system prompts, tool schemas, and conversation history versus genuinely new work.
2. **Value waste.** How much of what the model generates you actually use, versus how much gets discarded, ignored, or rewritten.

Usage dashboards from LLM providers show you totals. They don't show you whether that spend was productive. Tokenria closes that gap.

## What Tokenria Is Not

Tokenria does not reveal the internal mechanics of how a closed model (Claude, GPT, Gemini, etc.) decides which tokens to generate. That level of interpretability requires access to model internals, which API-based tools do not have and cannot fake. Tokenria focuses on what is actually measurable: token accounting, and the value you assign to what was produced.

## What It Does

Tokenria works in three layers, usable independently or together.

### 1. Token Accounting
Parses conversation logs or API response objects and breaks down token usage into categories: system prompt, tool definitions, conversation history, new input, cached tokens, and output. Computes cost per category using current model pricing, so you can see structurally where your spend is going.

### 2. Manual Value Tagging
A simple interface for marking which parts of a generated response you actually used, copied, acted on, or kept, versus what you discarded. Produces an adoption ratio (tokens used / tokens generated) per response and over time. This is the most honest signal of value in the tool, because it's based on your own judgment, not an automated guess.

### 3. Optional Auto-Annotation
A secondary, low-cost LLM pass that suggests which parts of a response are likely core answer, caveat, repetition, or unused filler, to speed up manual tagging. This is always presented as an estimate with a visible confidence label and is fully editable. It never replaces your own judgment as the source of truth.

## Output

Weekly or monthly reports covering:
- Total tokens and cost, broken down by category
- Adoption rate (how much generated output was actually useful)
- Cost per adopted token
- Trends over time, so you can see whether your usage is getting more or less efficient

## Design Principles

- **No black boxes.** Every number in a report traces back to either a token count or a decision you made. Nothing is presented as fact unless it's mechanically derived from usage data.
- **Local first.** Your conversation data and tagging decisions stay on your machine by default (SQLite storage). No requirement to send data to a third party to use the tool.
- **Model agnostic.** Works with any provider that exposes token usage metadata (input, output, cached tokens) in its API responses or exports.
- **Simple over clever.** The core value is a clear number you can point to and say "this is what I actually got for this spend." Anything that adds complexity without adding clarity gets left out.

## Status

Early development. Building in stages: token accounting first, manual tagging second, auto-annotation third.

## Why This Matters

If LLMs are part of your regular workflow, whether for work or personal projects, you should be able to answer a simple question with a real number, not a guess: "How much of what I paid for did I actually use?" Tokenria exists to make that question answerable.

## Contributing / Sponsorship

This project is being built in the open. If you work with LLMs regularly and want visibility into your own usage, or if you're interested in supporting development, watch this repo for updates as each stage ships.
