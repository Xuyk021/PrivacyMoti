import html
import json
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import streamlit as st
from openai import OpenAI

from prompts import (
    PRIVYPAL_SENSITIVITY_PROMPT,
    PRIVYPAL_REWRITE_PROMPT,
    SUMMARY_PROMPT,
    SUMMARY_REWRITE_PROMPT,
    FITNESS_PLAN_PROMPT,
)

from config.onboarding import ONBOARDING_QUESTIONS

st.set_page_config(
    page_title="FitPath",
    page_icon="",
    layout="centered",
    initial_sidebar_state="collapsed",
)

MODEL_NAME = "gpt-4o-mini"
CONDITION_NAME = "condition_1_multi_agent_privacy_coaching"


FIG_DIR = Path("fig")


def find_image(candidates: List[str]) -> Optional[str]:
    for name in candidates:
        path = FIG_DIR / name
        if path.exists():
            return str(path)
    return None


FITPATH_AVATAR = find_image(["fitpath_icon.png", "fitpath.png", "FitPath.png"])
PRIVYPAL_AVATAR = find_image(["privypal_icon.png", "privypal.png", "PrivyPal.png"])
USER_AVATAR = find_image(["user_icon.png", "user.png", "User.png"])
MEMORY_AVATAR = find_image(["memory_icon.png", "memory.png", "Memory.png"])


def get_openai_client() -> OpenAI:
    try:
        return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    except Exception:
        st.error("OPENAI_API_KEY was not found in Streamlit secrets.")
        st.stop()


def get_dynamodb_table():
    try:
        return boto3.resource(
            "dynamodb",
            region_name=st.secrets["AWS_DEFAULT_REGION"],
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        ).Table(st.secrets["DYNAMODB_TABLE_NAME"])
    except Exception as e:
        st.error(f"Failed to connect to DynamoDB: {e}")
        st.stop()


client = get_openai_client()
table = get_dynamodb_table()


def make_sort_key(role: str) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return f"{now}#{role}#{uuid.uuid4().hex[:6]}"


def generate_completion_code() -> str:
    return f"FitPath_{random.SystemRandom().randint(0, 99999):05d}"


def save_message(
    participant_id: str,
    role: str,
    content: str,
    turn_index: int,
    stage: str,
    agent: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
):
    item = {
        "participant_id": participant_id,
        "timestamp": make_sort_key(role),
        "role": role,
        "agent": agent or role,
        "content": content,
        "turn_index": turn_index,
        "stage": stage,
        "condition": CONDITION_NAME,
    }

    try:
        completion_code = st.session_state.get("completion_code")
        if completion_code:
            item["completion_code"] = completion_code
    except Exception:
        pass

    if extra:
        item["extra"] = json.dumps(extra, ensure_ascii=False)

    table.put_item(Item=item)






def call_json(system_prompt: str, user_text: str) -> Dict[str, Any]:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def call_text(system_prompt: str, user_text: str, temperature: float = 0.4) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return response.choices[0].message.content.strip()


def clean_plain_text(text: Any) -> str:
    text = str(text or "").strip()
    text = text.replace("<", "‹").replace(">", "›")
    return text


def review_privacy(user_input: str) -> Dict[str, Any]:
    try:
        sensitivity_data = call_json(PRIVYPAL_SENSITIVITY_PROMPT, user_input)
    except Exception:
        sensitivity_data = {
            "has_sensitive_info": False,
            "sensitive_info": [],
        }

    sensitive_info = sensitivity_data.get("sensitive_info", [])
    if not isinstance(sensitive_info, list):
        sensitive_info = []

    sensitive_info = [clean_plain_text(x) for x in sensitive_info if clean_plain_text(x)]
    has_sensitive_info = bool(sensitivity_data.get("has_sensitive_info", False)) or bool(sensitive_info)

    shared_payload = json.dumps(
        {
            "user_answer": user_input,
            "has_sensitive_info": has_sensitive_info,
            "sensitive_info": sensitive_info,
        },
        ensure_ascii=False,
    )

    if has_sensitive_info:
        try:
            alternative_description = call_text(PRIVYPAL_REWRITE_PROMPT, shared_payload, temperature=0.2)
        except Exception:
            alternative_description = user_input

        status_text = "Contains privacy-sensitive information"
        message_text = "This input appears to contain privacy-sensitive information. You may use the alternative description below to make it more abstract or general."
    else:
        alternative_description = ""
        status_text = "Does not contain privacy-sensitive information"
        message_text = "No privacy-sensitive information was detected. You are good to go."

    return {
        "has_private_info": has_sensitive_info,
        "private_info": sensitive_info,
        "privacy_status": status_text,
        "message_text": clean_plain_text(message_text),
        "alternative_description": clean_plain_text(alternative_description),
        "sensitivity_evaluation": True,
    }


def init_state():
    defaults = {
        "participant_id": None,
        "messages": [],
        "turn_index": 0,
        "question_index": 0,
        "answers": [],
        "stage": "welcome",
        "original_summary": None,
        "privacy_summary": None,
        "final_memory_summary": None,
        "summary_revision_used": False,
        "selected_summary_source": None,
        "pending_finalization": None,
        "is_processing_finalization": False,
        "final_notice_start_time": None,
        "final_notice_shown": False,
        "completion_code": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()


st.markdown(
    """
<style>
[data-testid="stSidebar"] {
    display: none;
}

.block-container {
    max-width: 860px;
    padding-top: 4.4rem;
    padding-bottom: 5rem;
}

.hero {
    padding: 1.25rem 1.35rem;
    border-radius: 1.3rem;
    background: linear-gradient(135deg, #f7f2ff 0%, #f8fbff 55%, #fff7ed 100%);
    border: 1px solid #eadfff;
    box-shadow: 0 12px 28px rgba(31, 41, 55, 0.06);
    margin-bottom: 1.5rem;
}

.hero-title {
    font-size: 1.85rem;
    font-weight: 750;
    margin-bottom: 0.25rem;
}

.hero-subtitle {
    color: #5f6472;
    font-size: 0.98rem;
    line-height: 1.5;
}

.agent-card {
    padding: 1rem 1.1rem;
    border-radius: 1.25rem;
    margin: 0.25rem 0 0.45rem 0;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.055);
    line-height: 1.55;
}

.fitpath-card {
    background: linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
    border: 1px solid #bfdbfe;
}

.privypal-card {
    background: linear-gradient(180deg, #fbf7ff 0%, #f3e8ff 100%);
    border: 1px solid #ddd6fe;
}

.memory-card {
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border: 1px solid #e2e8f0;
}

.agent-label {
    font-size: 0.92rem;
    font-weight: 800;
    letter-spacing: 0.02em;
    margin-bottom: 0.35rem;
}

.fitpath-label {
    color: #1d4ed8;
}

.privypal-label {
    color: #6d28d9;
}

.memory-label {
    color: #475569;
}

.question-pill {
    display: inline-block;
    font-size: 0.80rem;
    font-weight: 750;
    color: #1d4ed8;
    background: #dbeafe;
    border: 1px solid #bfdbfe;
    border-radius: 999px;
    padding: 0.18rem 0.55rem;
    margin-bottom: 0.45rem;
}

.sensitivity-tag {
    display: inline-block;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 800;
    padding: 0.18rem 0.55rem;
    margin-left: 0.35rem;
    vertical-align: middle;
}

.privacy-safe {
    color: #166534;
    background: #dcfce7;
    border: 1px solid #bbf7d0;
}

.privacy-sensitive {
    color: #991b1b;
    background: #fee2e2;
    border: 1px solid #fecaca;
}

.section-label {
    font-size: 0.8rem;
    font-weight: 800;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 0.75rem;
    margin-bottom: 0.2rem;
}

.card-text {
    margin: 0.2rem 0 0.55rem 0;
    white-space: pre-wrap;
}

.summary-card {
    height: 460px;
    padding: 1rem;
    border-radius: 1.2rem;
    border: 1px solid #e5e7eb;
    background: #ffffff;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.045);
    display: flex;
    flex-direction: column;
    margin-bottom: 0.75rem;
    overflow-y: auto;
}

.summary-card.original {
    border-color: #bfdbfe;
    background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.summary-card.privacy {
    border-color: #ddd6fe;
    background: linear-gradient(180deg, #ffffff 0%, #fbf7ff 100%);
}

.summary-title {
    font-weight: 800;
    margin-bottom: 0.25rem;
}

.summary-caption {
    color: #6b7280;
    font-size: 0.88rem;
    margin-bottom: 0.8rem;
}

.stButton > button {
    border-radius: 999px;
    height: 2.7rem;
    font-weight: 650;
}

div[data-testid="stDialog"] div[data-testid="stVerticalBlockBorderWrapper"] {
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)


def safe_html_text(text: Any) -> str:
    return html.escape(str(text or "")).replace("\n", "<br>")


def render_fitpath_card(content: str, question_number: Optional[int] = None):
    question_html = ""
    if question_number is not None:
        question_html = (
            f"<div class='question-pill'>"
            f"Question {question_number} of {len(ONBOARDING_QUESTIONS)}"
            f"</div>"
        )

    card_html = (
        "<div class='agent-card fitpath-card'>"
        "<div class='agent-label fitpath-label'>FitPath</div>"
        f"{question_html}"
        f"<div class='card-text'>{safe_html_text(content)}</div>"
        "</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def render_memory_card(source: str, summary: str):
    content = f"Selected summary: {source}\n\nThis version will be saved to memory.\n\n{summary}"
    card_html = (
        "<div class='agent-card memory-card'>"
        "<div class='agent-label memory-label'>Memory</div>"
        f"<div class='card-text'>{safe_html_text(content)}</div>"
        "</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def render_memory_notice_card(content: str):
    card_html = (
        "<div class='agent-card memory-card'>"
        "<div class='agent-label memory-label'>Memory</div>"
        f"<div class='card-text'>{safe_html_text(content)}</div>"
        "</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def render_privypal_card(result: Dict[str, Any]):
    has_private_info = bool(result.get("has_private_info", False))
    tag_class = "privacy-sensitive" if has_private_info else "privacy-safe"
    status_text = clean_plain_text(
        result.get("privacy_status", "包含隐私信息" if has_private_info else "不包含隐私信息")
    )
    status_icon = "" if has_private_info else "✓ "

    private_info = result.get("private_info", [])
    if not isinstance(private_info, list):
        private_info = []

    private_text = ", ".join([clean_plain_text(x) for x in private_info]) if private_info else "No specific sensitive information identified."
    message_text = clean_plain_text(result.get("message_text", ""))
    alternative_description = clean_plain_text(result.get("alternative_description", ""))

    card_html = (
        "<div class='agent-card privypal-card'>"
        "<div class='agent-label privypal-label'>"
        "PrivyPal privacy review"
        f"<span class='sensitivity-tag {tag_class}'>{status_icon}{safe_html_text(status_text)}</span>"
        "</div>"
        "<div class='section-label'>Privacy check result</div>"
        f"<div class='card-text'>{safe_html_text(message_text)}</div>"
        "<div class='section-label'>Sensitive private information detected</div>"
        f"<div class='card-text'>{safe_html_text(private_text)}</div>"
    )

    if has_private_info and alternative_description:
        card_html += (
            "<div class='section-label'>Alternative description</div>"
            f"<div class='card-text'>{safe_html_text(alternative_description)}</div>"
        )

    card_html += "</div>"
    st.markdown(card_html, unsafe_allow_html=True)


def append_message(
    role: str,
    content: str,
    agent: str,
    msg_type: str = "text",
    avatar: Optional[str] = None,
    question_number: Optional[int] = None,
    privacy_result: Optional[Dict[str, Any]] = None,
    selection_source: Optional[str] = None,
    stage: Optional[str] = None,
    save: bool = True,
    extra: Optional[Dict[str, Any]] = None,
):
    msg = {
        "role": role,
        "content": content,
        "agent": agent,
        "type": msg_type,
        "avatar": avatar,
        "question_number": question_number,
        "privacy_result": privacy_result,
        "selection_source": selection_source,
    }

    st.session_state.messages.append(msg)

    if save and st.session_state.participant_id:
        save_message(
            participant_id=st.session_state.participant_id,
            role=role,
            content=content,
            turn_index=st.session_state.turn_index,
            stage=stage or st.session_state.stage,
            agent=agent,
            extra=extra,
        )


def render_message(msg: Dict[str, Any]):
    role = "user" if msg["role"] == "user" else "assistant"
    avatar = msg.get("avatar")

    with st.chat_message(role, avatar=avatar):
        if msg["type"] == "fitpath_card":
            render_fitpath_card(msg["content"], question_number=msg.get("question_number"))
        elif msg["type"] == "privypal_card":
            render_privypal_card(msg["privacy_result"] or {})
        elif msg["type"] == "memory_card":
            render_memory_card(msg.get("selection_source", "Selected version"), msg["content"])
        elif msg["type"] == "memory_notice_card":
            render_memory_notice_card(msg["content"])
        else:
            st.markdown(clean_plain_text(msg["content"]))


def render_messages():
    for msg in st.session_state.messages:
        render_message(msg)


def current_question() -> Dict[str, str]:
    return ONBOARDING_QUESTIONS[st.session_state.question_index]


def ask_current_question():
    q = current_question()
    append_message(
        role="assistant",
        content=q["text"],
        agent="FitPath",
        msg_type="fitpath_card",
        avatar=FITPATH_AVATAR,
        question_number=st.session_state.question_index + 1,
        stage="onboarding_question",
        save=True,
    )


def build_answers_payload() -> str:
    lines = []
    for i, item in enumerate(st.session_state.answers, start=1):
        lines.append(
            f"Q{i} ({item['question_id']}): {item['question']}\n"
            f"A{i}: {item['answer']}"
        )
    return "\n\n".join(lines)


def create_summaries():
    answers_payload = build_answers_payload()

    original_summary = clean_plain_text(
        call_text(SUMMARY_PROMPT, answers_payload, temperature=0.2)
    )
    privacy_summary = clean_plain_text(
        call_text(SUMMARY_REWRITE_PROMPT, original_summary, temperature=0.2)
    )

    st.session_state.original_summary = original_summary
    st.session_state.privacy_summary = privacy_summary
    st.session_state.stage = "summary_choice"

    append_message(
        role="assistant",
        content=(
            "Thank you. Here is a quick summary of your needs, goals, and limitations. "
            "Please choose which version should be saved to memory."
        ),
        agent="FitPath",
        msg_type="fitpath_card",
        avatar=FITPATH_AVATAR,
        stage="summary_intro",
        save=True,
    )


def queue_memory_finalization(final_summary: str, source_label: str):
    """Start a step-by-step finalization flow."""
    final_summary = clean_plain_text(final_summary)

    st.session_state.pending_finalization = {
        "summary": final_summary,
        "source_label": source_label,
        "step": 0,
    }
    st.session_state.final_memory_summary = final_summary
    st.session_state.selected_summary_source = source_label
    st.session_state.stage = "finalizing"
    st.session_state.is_processing_finalization = False

def process_memory_finalization():
    """
    Append exactly one finalization message per rerun.

    This creates the staged 0.5s appearance:
    1. selected memory summary
    2. memory updated
    3. recommending message
    4. final weekly plan

    It avoids temporary st.chat_message containers, so there should be no blank
    assistant bubbles.
    """
    pending = st.session_state.get("pending_finalization")
    if not pending:
        return

    if st.session_state.get("is_processing_finalization"):
        return

    st.session_state.is_processing_finalization = True

    final_summary = clean_plain_text(pending.get("summary", ""))
    source_label = clean_plain_text(pending.get("source_label", "Selected summary"))
    step = int(pending.get("step", 0))

    if step == 0:
        append_message(
            role="assistant",
            content=final_summary,
            agent="Memory",
            msg_type="memory_card",
            avatar=MEMORY_AVATAR,
            selection_source=source_label,
            stage="summary_selected",
            save=True,
            extra={
                "selected_summary": final_summary,
                "selection_source": source_label,
            },
        )
        st.session_state.pending_finalization["step"] = 1
        st.session_state.is_processing_finalization = False
        time.sleep(0.5)
        st.rerun()

    elif step == 1:
        append_message(
            role="assistant",
            content="Memory updated.",
            agent="Memory",
            msg_type="memory_notice_card",
            avatar=MEMORY_AVATAR,
            stage="memory_updated",
            save=True,
        )
        st.session_state.pending_finalization["step"] = 2
        st.session_state.is_processing_finalization = False
        time.sleep(0.5)
        st.rerun()

    elif step == 2:
        append_message(
            role="assistant",
            content="Recommending your fitness plan.",
            agent="FitPath",
            msg_type="fitpath_card",
            avatar=FITPATH_AVATAR,
            stage="recommendation_start",
            save=True,
        )
        st.session_state.pending_finalization["step"] = 3
        st.session_state.is_processing_finalization = False
        time.sleep(0.5)
        st.rerun()

    elif step == 3:
        with st.spinner("FitPath is creating your weekly plan..."):
            plan = clean_plain_text(
                call_text(FITNESS_PLAN_PROMPT, final_summary, temperature=0.5)
            )

        append_message(
            role="assistant",
            content=plan,
            agent="FitPath",
            msg_type="fitpath_card",
            avatar=FITPATH_AVATAR,
            stage="fitness_plan",
            save=True,
            extra={
                "final_memory_summary": final_summary,
                "selection_source": source_label,
            },
        )
        st.session_state.stage = "complete"
        st.session_state.pending_finalization = None
        st.session_state.is_processing_finalization = False

        st.session_state.final_notice_start_time = time.time()
        st.session_state.final_notice_shown = False

        st.rerun()

st.markdown(
    """
<div class="hero">
    <div class="hero-title">FitPath</div>
    <div class="hero-subtitle">
        A personalized fitness planning assistant with independent privacy coaching from PrivyPal.
    </div>
</div>
""",
    unsafe_allow_html=True,
)


@st.dialog("Welcome to FitPath")
def welcome_dialog():
    st.markdown("### FitPath")
    st.markdown(
        """
FitPath is a personalized conversational fitness planning AI assistant.

It includes a memory feature that helps provide a more personalized fitness plan.

FitPath also collaborates with **PrivyPal**, an independent privacy-support agent.
PrivyPal operates independently and does not use memory.

Please enter your Prolific ID to begin.
        """
    )

    pid = st.text_input("Prolific ID", placeholder="Enter your Prolific ID")

    if st.button("Start", use_container_width=True):
        pid = pid.strip()
        if not pid:
            st.warning("Please enter a valid Prolific ID.")
            return

        st.session_state.participant_id = pid
        st.session_state.turn_index = 0
        st.session_state.question_index = 0
        st.session_state.answers = []
        st.session_state.messages = []
        st.session_state.stage = "onboarding"
        st.session_state.original_summary = None
        st.session_state.privacy_summary = None
        st.session_state.final_memory_summary = None
        st.session_state.summary_revision_used = False
        st.session_state.selected_summary_source = None
        st.session_state.pending_finalization = None
        st.session_state.is_processing_finalization = False
        st.session_state.final_notice_start_time = None
        st.session_state.final_notice_shown = False
        st.session_state.completion_code = generate_completion_code()

        save_message(
            participant_id=pid,
            role="system",
            content="Participant started Condition 1.",
            turn_index=0,
            stage="participant_start",
            agent="system",
            extra={
                "condition": CONDITION_NAME,
                "completion_code": st.session_state.completion_code,
            },
        )

        ask_current_question()
        st.rerun()


if st.session_state.participant_id is None:
    welcome_dialog()
    st.stop()


render_messages()

if st.session_state.stage == "complete":
    if st.session_state.final_notice_start_time is not None:
        elapsed = time.time() - st.session_state.final_notice_start_time

        if elapsed >= 10:
            completion_code = st.session_state.get("completion_code") or generate_completion_code()
            st.session_state.completion_code = completion_code
            st.warning(
                "You have completed the AI tool interaction. Please return the following code to the questionnaire and proceed to the last part of the study. "
                f"Code: {completion_code}"
            )
            st.session_state.final_notice_shown = True
        elif not st.session_state.final_notice_shown:
            time.sleep(10 - elapsed)
            st.rerun()

if st.session_state.stage == "finalizing":
    process_memory_finalization()
    st.stop()


if st.session_state.stage == "summary_choice":
    st.markdown("### Choose what to save to memory")

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        summary_html = (
            "<div class='summary-card original'>"
            "<div class='summary-title'>Original summary</div>"
            "<div class='summary-caption'>More detailed version based directly on your answers.</div>"
            f"<div class='card-text'>{safe_html_text(st.session_state.original_summary or '')}</div>"
            "</div>"
        )
        st.markdown(summary_html, unsafe_allow_html=True)

        use_original = st.button(
            "Use original summary",
            use_container_width=True,
            key="use_original_summary",
        )

    with col2:
        summary_html = (
            "<div class='summary-card privacy'>"
            "<div class='summary-title'>Privacy-protective summary</div>"
            "<div class='summary-caption'>More generalized version prepared by PrivyPal.</div>"
            f"<div class='card-text'>{safe_html_text(st.session_state.privacy_summary or '')}</div>"
            "</div>"
        )
        st.markdown(summary_html, unsafe_allow_html=True)

        use_privacy = st.button(
            "Use privacy-protective summary",
            use_container_width=True,
            key="use_privacy_summary",
        )

    revised_summary = st.chat_input("Or type one revised summary here...")

    if use_original:
        save_message(
            participant_id=st.session_state.participant_id,
            role="user_action",
            content="User selected original summary.",
            turn_index=st.session_state.turn_index,
            stage="summary_choice",
            agent="user",
            extra={
                "selection_source": "Original summary",
                "selected_summary": st.session_state.original_summary,
            },
        )
        queue_memory_finalization(st.session_state.original_summary, "Original summary")
        st.rerun()

    if use_privacy:
        save_message(
            participant_id=st.session_state.participant_id,
            role="user_action",
            content="User selected privacy-protective summary.",
            turn_index=st.session_state.turn_index,
            stage="summary_choice",
            agent="user",
            extra={
                "selection_source": "Privacy-protective summary",
                "selected_summary": st.session_state.privacy_summary,
            },
        )
        queue_memory_finalization(st.session_state.privacy_summary, "Privacy-protective summary")
        st.rerun()

    if revised_summary:
        revised_summary = clean_plain_text(revised_summary)
        if revised_summary:
            st.session_state.turn_index += 1

            user_msg = {
                "role": "user",
                "content": revised_summary,
                "agent": "user",
                "type": "text",
                "avatar": USER_AVATAR,
                "question_number": None,
                "privacy_result": None,
                "selection_source": None,
            }

            st.session_state.messages.append(user_msg)
            render_message(user_msg)

            save_message(
                participant_id=st.session_state.participant_id,
                role="user",
                content=revised_summary,
                turn_index=st.session_state.turn_index,
                stage="summary_revision",
                agent="user",
                extra={
                    "revision_type": "manual_summary_revision",
                    "revision_used": True,
                },
            )

            if st.session_state.summary_revision_used:
                warning = "You have already used your one revision. Please choose one of the two summary versions above."
                append_message(
                    role="assistant",
                    content=warning,
                    agent="FitPath",
                    msg_type="fitpath_card",
                    avatar=FITPATH_AVATAR,
                    stage="revision_limit",
                    save=True,
                )
            else:
                st.session_state.summary_revision_used = True
                queue_memory_finalization(revised_summary, "User-revised summary")

            st.rerun()

    st.stop()


if st.session_state.stage == "onboarding":
    placeholder = "Type your answer..."
elif st.session_state.stage == "complete":
    placeholder = "You may type a follow-up message..."
else:
    placeholder = "Type your message..."

user_input = st.chat_input(placeholder)

if user_input:
    user_input = clean_plain_text(user_input)

    if not user_input:
        st.stop()

    st.session_state.turn_index += 1

    user_msg = {
        "role": "user",
        "content": user_input,
        "agent": "user",
        "type": "text",
        "avatar": USER_AVATAR,
        "question_number": None,
        "privacy_result": None,
        "selection_source": None,
    }

    st.session_state.messages.append(user_msg)

    save_message(
        participant_id=st.session_state.participant_id,
        role="user",
        content=user_input,
        turn_index=st.session_state.turn_index,
        stage=st.session_state.stage,
        agent="user",
    )

    render_message(user_msg)

    if st.session_state.stage == "onboarding":
        q = current_question()

        st.session_state.answers.append({
            "question_id": q["id"],
            "question": q["text"],
            "answer": user_input,
        })

        with st.chat_message("assistant", avatar=PRIVYPAL_AVATAR):
            with st.spinner("PrivyPal is reviewing your answer..."):
                privacy_result = review_privacy(user_input)

            render_privypal_card(privacy_result)

        append_message(
            role="assistant",
            content="PrivyPal privacy review",
            agent="PrivyPal",
            msg_type="privypal_card",
            avatar=PRIVYPAL_AVATAR,
            privacy_result=privacy_result,
            stage="per_question_privacy_sensitivity_check",
            save=True,
            extra=privacy_result,
        )

        st.session_state.question_index += 1

        if st.session_state.question_index < len(ONBOARDING_QUESTIONS):
            ask_current_question()
        else:
            with st.chat_message("assistant", avatar=FITPATH_AVATAR):
                with st.spinner("FitPath is summarizing your onboarding answers..."):
                    create_summaries()

        st.rerun()

    elif st.session_state.stage == "complete":
        followup_prompt = (
            "The user has already received a weekly fitness plan. "
            "Respond briefly to their follow-up. If they ask for changes, revise the plan concisely.\n\n"
            f"Final memory summary:\n{st.session_state.final_memory_summary}\n\n"
            f"User follow-up:\n{user_input}"
        )

        with st.chat_message("assistant", avatar=FITPATH_AVATAR):
            with st.spinner("FitPath is updating the recommendation..."):
                reply = clean_plain_text(
                    call_text(FITNESS_PLAN_PROMPT, followup_prompt, temperature=0.5)
                )

            render_fitpath_card(reply)

        append_message(
            role="assistant",
            content=reply,
            agent="FitPath",
            msg_type="fitpath_card",
            avatar=FITPATH_AVATAR,
            stage="followup",
            save=True,
        )

        st.rerun()