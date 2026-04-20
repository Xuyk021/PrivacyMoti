import json
import re
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI


# -----------------------------
# App Config
# -----------------------------
st.set_page_config(
    page_title="FitPath",
    page_icon="💬",
    layout="centered",
)

# -----------------------------
# OpenAI Client
# -----------------------------
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception:
    st.error(
        "OPENAI_API_KEY was not found in .streamlit/secrets.toml. "
        "Please add it before running the app."
    )
    st.stop()


# -----------------------------
# Constants
# -----------------------------
APP_TITLE = "FitPath"
MODEL_NAME = "gpt-4o-mini"

WELCOME_MESSAGE = (
    "Hi, I’m FitPath. I can help you build a personalized weekly fitness plan.\n\n"
    "Before we get started, please note that this system includes a memory feature, "
    "and your inputs may be stored and used for future model training.\n\n"
    "Tell me about your fitness goal, and I’ll help you move forward."
)

PRIVACY_DETECTION_SYSTEM_PROMPT = """
You are a privacy-aware fitness assistant support module.

Your task is to inspect the user's latest message and decide whether it contains
personal or sensitive information that should be minimized before sending it to
a fitness planning assistant.

Sensitive or potentially identifying information includes but is not limited to:
- full names
- email addresses
- phone numbers
- exact home addresses
- precise locations
- health or medical conditions
- age when tied to identity
- financial details
- employment details
- information about minors
- any combination of details that could identify a person

Important rules:
- Do not invent sensitive information that is not present.
- Be calm and non-alarmist.
- Preserve the user's intent.
- Do not over-remove useful context that helps fitness planning.
- If the message is low-risk, say so.
- This step should NOT produce the actual fitness plan.

Return ONLY valid JSON with this schema:
{
  "has_sensitive_info": true or false,
  "risk_level": "low" | "moderate" | "high",
  "reason": "brief explanation",
  "highlight_spans": [
    {"text": "...", "label": "..."}
  ],
  "revised_prompt": "privacy-preserving rewrite that preserves intent",
  "should_request_final_prompt": true or false
}
"""

FITNESS_PLANNING_SYSTEM_PROMPT = """
You are FitPath, a helpful and encouraging fitness planning AI assistant.

Your job is to create a practical, personalized weekly fitness plan based on
the user's final prompt.

Guidelines:
- Be supportive, clear, and realistic.
- Ask for clarification only if essential.
- Do not mention privacy analysis unless the user asks.
- If the user gave a revised prompt, use it naturally.
- Organize the plan in a clean structure.
- Include weekly schedule, workout focus, basic progression, and recovery advice.
- Avoid medical claims.
- If the user mentions serious health issues or unsafe exercise conditions,
  recommend consulting a professional without becoming alarmist.
"""

PRIVACY_RESPONSE_SYSTEM_PROMPT = """
You are FitPath, a conversational fitness planning AI assistant.

You are replying to a user's first message before generating a fitness plan.
Do not generate the actual plan yet.

If there is privacy risk:
- Briefly and calmly explain that the message includes personal or sensitive details.
- Keep the tone natural and chatbot-like.
- Invite the user to send a final version using either the original or the safer rewrite.

If there is low risk:
- Say the message looks low-risk.
- Optionally mention a slightly generalized version if useful.
- Invite the user to send the final prompt so you can create the fitness plan.

Keep the response concise and friendly.
"""

# -----------------------------
# Session State
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": WELCOME_MESSAGE}
    ]

if "awaiting_final_prompt" not in st.session_state:
    st.session_state.awaiting_final_prompt = False

if "last_privacy_result" not in st.session_state:
    st.session_state.last_privacy_result = None

if "final_prompt" not in st.session_state:
    st.session_state.final_prompt = None


# -----------------------------
# Utility Functions
# -----------------------------
def call_openai_json(system_prompt: str, user_input: str) -> Dict[str, Any]:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
    )
    content = response.choices[0].message.content
    return json.loads(content)


def call_openai_text(messages: List[Dict[str, str]], temperature: float = 0.5) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=temperature,
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def normalize_highlight_spans(spans: Any) -> List[Dict[str, str]]:
    if not isinstance(spans, list):
        return []

    normalized = []
    for item in spans:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        label = str(item.get("label", "Sensitive")).strip()
        if text:
            normalized.append({"text": text, "label": label})
    return normalized


def highlight_sensitive_text(text: str, spans: List[Dict[str, str]]) -> str:
    """
    Return HTML string with highlighted sensitive spans.
    """
    if not spans:
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return f"<div>{escaped}</div>"

    escaped_text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    # Sort longer spans first to reduce nested conflicts
    unique_spans = []
    seen = set()
    for s in spans:
        key = (s["text"], s["label"])
        if key not in seen:
            seen.add(key)
            unique_spans.append(s)

    unique_spans.sort(key=lambda x: len(x["text"]), reverse=True)

    html = escaped_text
    for span in unique_spans:
        raw_text = span["text"]
        label = span["label"]

        raw_text_escaped = (
            raw_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        badge = (
            f'<span style="font-size:0.75rem; color:#7c2d12; '
            f'background:#ffedd5; border:1px solid #fdba74; '
            f'padding:0.1rem 0.35rem; border-radius:999px; margin-left:0.35rem;">'
            f'{label}</span>'
        )

        replacement = (
            f'<mark style="background-color:#fef3c7; padding:0.1rem 0.2rem; '
            f'border-radius:0.3rem;">{raw_text_escaped}</mark>{badge}'
        )

        pattern = re.escape(raw_text_escaped)
        html = re.sub(pattern, replacement, html, count=1)

    return f"<div style='line-height:1.8;'>{html}</div>"


def render_privacy_card(original_text: str, privacy_result: Dict[str, Any]) -> None:
    has_sensitive_info = privacy_result.get("has_sensitive_info", False)
    reason = privacy_result.get("reason", "")
    revised_prompt = privacy_result.get("revised_prompt", "")
    spans = normalize_highlight_spans(privacy_result.get("highlight_spans", []))
    risk_level = privacy_result.get("risk_level", "low")

    if has_sensitive_info:
        risk_color = {
            "moderate": "#b45309",
            "high": "#b91c1c",
        }.get(risk_level, "#b45309")

        st.markdown(
            f"""
            <div style="
                border:1px solid #f3d19c;
                background:#fffaf0;
                padding:1rem;
                border-radius:0.9rem;
                margin-top:0.5rem;
                margin-bottom:0.5rem;
            ">
                <div style="font-weight:600; font-size:1rem; margin-bottom:0.4rem;">
                    Privacy Review
                </div>
                <div style="color:{risk_color}; font-weight:600; margin-bottom:0.4rem;">
                    Risk level: {risk_level.capitalize()}
                </div>
                <div style="color:#444; margin-bottom:0.8rem;">
                    {reason}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("**Your original message**")
        st.markdown(
            f"""
            <div style="
                border:1px solid #e5e7eb;
                background:#ffffff;
                padding:0.9rem 1rem;
                border-radius:0.8rem;
                margin-bottom:0.8rem;
            ">
                {highlight_sensitive_text(original_text, spans)}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("**Safer revised version**")
        st.markdown(
            f"""
            <div style="
                border:1px solid #dbeafe;
                background:#f8fbff;
                padding:0.9rem 1rem;
                border-radius:0.8rem;
                margin-bottom:0.5rem;
                white-space:pre-wrap;
            ">{revised_prompt}</div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="
                border:1px solid #d1fae5;
                background:#f0fdf4;
                padding:1rem;
                border-radius:0.9rem;
                margin-top:0.5rem;
                margin-bottom:0.5rem;
            ">
                <div style="font-weight:600; font-size:1rem; margin-bottom:0.4rem;">
                    Privacy Review
                </div>
                <div style="color:#166534; font-weight:600; margin-bottom:0.4rem;">
                    Risk level: Low
                </div>
                <div style="color:#444; margin-bottom:0.5rem;">
                    {reason}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if revised_prompt and revised_prompt.strip() != original_text.strip():
            st.markdown("**Optional generalized version**")
            st.markdown(
                f"""
                <div style="
                    border:1px solid #dbeafe;
                    background:#f8fbff;
                    padding:0.9rem 1rem;
                    border-radius:0.8rem;
                    margin-bottom:0.5rem;
                    white-space:pre-wrap;
                ">{revised_prompt}</div>
                """,
                unsafe_allow_html=True,
            )


def build_privacy_assistant_reply(
    user_text: str,
    privacy_result: Dict[str, Any],
) -> str:
    payload = {
        "user_message": user_text,
        "privacy_result": privacy_result,
    }

    return call_openai_text(
        messages=[
            {"role": "system", "content": PRIVACY_RESPONSE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.4,
    )


def generate_fitness_plan(final_prompt: str) -> str:
    return call_openai_text(
        messages=[
            {"role": "system", "content": FITNESS_PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": final_prompt},
        ],
        temperature=0.7,
    )


# -----------------------------
# UI Header
# -----------------------------
st.markdown(
    f"""
    <div style="padding-top:0.2rem; padding-bottom:0.6rem;">
        <div style="font-size:1.7rem; font-weight:700;">{APP_TITLE}</div>
        <div style="color:#6b7280; font-size:0.98rem;">
            Chat naturally about your fitness goals.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Render Chat History
# -----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg.get("privacy_result") and msg.get("original_user_input"):
            render_privacy_card(
                original_text=msg["original_user_input"],
                privacy_result=msg["privacy_result"],
            )

# -----------------------------
# Chat Input
# -----------------------------
user_input = st.chat_input("Tell me about your fitness goal...")

if user_input:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Branch 1: waiting for final prompt -> generate plan
    if st.session_state.awaiting_final_prompt:
        st.session_state.final_prompt = user_input

        with st.chat_message("assistant"):
            with st.spinner("Creating your weekly fitness plan..."):
                plan = generate_fitness_plan(user_input)
            st.markdown(plan)

        st.session_state.messages.append(
            {"role": "assistant", "content": plan}
        )
        st.session_state.awaiting_final_prompt = False
        st.session_state.last_privacy_result = None

    # Branch 2: first-stage conversational privacy review
    else:
        with st.chat_message("assistant"):
            with st.spinner("Reviewing your message..."):
                privacy_result = call_openai_json(
                    PRIVACY_DETECTION_SYSTEM_PROMPT,
                    user_input,
                )

                # Defensive normalization
                privacy_result["has_sensitive_info"] = bool(
                    privacy_result.get("has_sensitive_info", False)
                )
                privacy_result["risk_level"] = str(
                    privacy_result.get("risk_level", "low")
                ).lower()
                privacy_result["reason"] = str(
                    privacy_result.get("reason", "I reviewed your message for privacy risk.")
                )
                privacy_result["revised_prompt"] = str(
                    privacy_result.get("revised_prompt", user_input)
                )
                privacy_result["should_request_final_prompt"] = bool(
                    privacy_result.get("should_request_final_prompt", True)
                )
                privacy_result["highlight_spans"] = normalize_highlight_spans(
                    privacy_result.get("highlight_spans", [])
                )

                assistant_reply = build_privacy_assistant_reply(
                    user_input,
                    privacy_result,
                )

            st.markdown(assistant_reply)
            render_privacy_card(user_input, privacy_result)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": assistant_reply,
                "privacy_result": privacy_result,
                "original_user_input": user_input,
            }
        )

        st.session_state.last_privacy_result = privacy_result
        st.session_state.awaiting_final_prompt = True