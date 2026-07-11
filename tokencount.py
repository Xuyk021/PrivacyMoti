import tiktoken
from prompts import PRIVYPAL_SENSITIVITY_PROMPT

def count_tokens(text, model="gpt-4o"):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("o200k_base")

    return len(encoding.encode(text))


token_count = count_tokens(
    PRIVYPAL_SENSITIVITY_PROMPT,
    model="gpt-4o"
)

print(f"Prompt tokens: {token_count}")