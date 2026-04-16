import streamlit as st
from openai import OpenAI

# Page setup
st.set_page_config(page_title="OpenAI Chatbot", page_icon="💬", layout="centered")

st.title("OpenAI Chatbot")

# Load API key from Streamlit secrets
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ]

# Display existing messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
user_input = st.chat_input("Type your message here...")

if user_input:
    # Store and display user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Generate assistant response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=st.session_state.messages,
                temperature=0.7,
            )
            assistant_reply = response.choices[0].message.content
            st.markdown(assistant_reply)

    # Store assistant response
    st.session_state.messages.append(
        {"role": "assistant", "content": assistant_reply}
    )

# Optional button to clear chat history
if st.button("Clear chat"):
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ]
    st.rerun()