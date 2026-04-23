import uuid
from datetime import datetime, timezone

import boto3
import streamlit as st


st.set_page_config(page_title="Minimal DynamoDB Chat", page_icon="💬", layout="centered")


def get_table():
    return boto3.resource(
        "dynamodb",
        region_name=st.secrets["AWS_DEFAULT_REGION"],
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
    ).Table(st.secrets["DYNAMODB_TABLE_NAME"])


def make_sort_key(role: str) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return f"{now}#{role}#{uuid.uuid4().hex[:6]}"


def save_message(table, participant_id: str, role: str, content: str, turn_index: int):
    table.put_item(
        Item={
            "participant_id": participant_id,
            "timestamp": make_sort_key(role),
            "role": role,
            "content": content,
            "turn_index": turn_index,
        }
    )


def simple_bot_reply(text: str) -> str:
    text_lower = text.strip().lower()

    if not text_lower:
        return "Please type a message."

    if text_lower in ["hi", "hello", "hey"]:
        return "Hello. This is a minimal DynamoDB test bot."

    if "name" in text_lower:
        return "I am a simple test bot."

    if "help" in text_lower:
        return "You can type any message. I will reply and save the conversation."

    if "bye" in text_lower:
        return "Goodbye. Your conversation has been saved."

    return f"You said: {text}"


if "participant_id" not in st.session_state:
    st.session_state.participant_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "turn_index" not in st.session_state:
    st.session_state.turn_index = 0


st.title("Minimal DynamoDB Chat")

try:
    table = get_table()
except Exception as e:
    st.error(f"Failed to connect to DynamoDB: {e}")
    st.stop()


if st.session_state.participant_id is None:
    st.subheader("Enter Participant ID")

    with st.form("participant_form"):
        pid = st.text_input("Participant ID")
        submitted = st.form_submit_button("Start")

    if submitted:
        pid = pid.strip()

        if not pid:
            st.warning("Please enter a valid Participant ID.")
            st.stop()

        st.session_state.participant_id = pid

        welcome = "Welcome. You can start chatting now."
        st.session_state.messages.append(
            {"role": "assistant", "content": welcome}
        )

        try:
            save_message(table, pid, "assistant", welcome, 0)
        except Exception as e:
            st.error(f"Failed to write welcome message: {e}")
            st.stop()

        st.rerun()

    st.stop()


st.caption(f"Participant ID: {st.session_state.participant_id}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Type your message...")

if user_input:
    st.session_state.turn_index += 1
    turn = st.session_state.turn_index

    st.session_state.messages.append(
        {"role": "user", "content": user_input}
    )

    try:
        save_message(table, st.session_state.participant_id, "user", user_input, turn)
    except Exception as e:
        st.error(f"Failed to write user message: {e}")
        st.stop()

    reply = simple_bot_reply(user_input)

    st.session_state.messages.append(
        {"role": "assistant", "content": reply}
    )

    try:
        save_message(table, st.session_state.participant_id, "assistant", reply, turn)
    except Exception as e:
        st.error(f"Failed to write assistant message: {e}")
        st.stop()

    st.rerun()