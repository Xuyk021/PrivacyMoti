import csv
import json
import tomllib
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from openai import OpenAI


OUTPUT_DIR = Path("rewrite_outputs")
DATASET_DIR = OUTPUT_DIR / "datasets"
RESULT_DIR = OUTPUT_DIR / "results"

DATASET_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "gpt-4o-mini"


def load_openai_key():
    with open(".streamlit/secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    return secrets["OPENAI_API_KEY"]


@st.cache_resource
def get_client():
    return OpenAI(api_key=load_openai_key())


client = get_client()


def ask_chatgpt(prompt: str) -> str:
    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )
    return response.output_text.strip()


def generate_examples(question: str, n: int):
    prompt = f"""
Generate {n} realistic English user responses to the following onboarding question.

Question:
{question}

Requirements:
- Each response should be written in first person.
- Responses should be diverse and realistic.
- Include a mix of responses with privacy-sensitive details and less sensitive details.
- When natural, include details related to health, mental health, family responsibilities, caregiving, location, workplace, school, income, or identifying demographic combinations.
- Do not make every response extreme.
- Return ONLY a valid JSON list of strings.
"""

    text = ask_chatgpt(prompt)

    try:
        examples = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"GPT did not return valid JSON:\n{text}")

    if not isinstance(examples, list):
        raise ValueError(f"GPT output is not a list:\n{text}")

    return examples


def run_rewrite(original_answer: str, rewrite_prompt: str):
    final_prompt = f"""
{rewrite_prompt}

User answer:
{original_answer}
"""
    return ask_chatgpt(final_prompt)


def save_csv(path: Path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_text(path: Path, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def list_csv_files(folder: Path):
    return sorted(folder.glob("*.csv"), reverse=True)


def load_dataset(path: Path):
    return pd.read_csv(path)


st.set_page_config(
    page_title="PrivyPal Rewrite Prompt Tester",
    page_icon="🛡️",
    layout="wide",
)

st.title("PrivyPal Rewrite Prompt Tester")
st.caption("Generate fixed original examples once, then test different rewrite prompts on the same dataset.")


tab_generate, tab_rewrite = st.tabs(
    [
        "1. Generate original dataset",
        "2. Test rewrite prompt",
    ]
)


with tab_generate:
    st.subheader("Generate original examples")

    question = st.text_area(
        "Question",
        height=120,
        placeholder="Example: What does a typical weekday look like for you?",
    )

    n = st.number_input(
        "Number of examples",
        min_value=1,
        max_value=100,
        value=20,
        step=1,
    )

    dataset_name = st.text_input(
        "Dataset name",
        placeholder="Example: typical_day_test",
    )

    if st.button("Generate dataset", type="primary"):
        if not question.strip():
            st.warning("Please enter a question.")
            st.stop()

        if not dataset_name.strip():
            dataset_name = "dataset"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dataset_file = DATASET_DIR / f"{dataset_name}_{timestamp}.csv"
        setting_file = DATASET_DIR / f"{dataset_name}_{timestamp}_settings.txt"

        with st.spinner("Generating examples..."):
            try:
                examples = generate_examples(question, int(n))
            except Exception as e:
                st.error(str(e))
                st.stop()

        rows = []
        for i, answer in enumerate(examples, start=1):
            rows.append(
                {
                    "id": i,
                    "question": question,
                    "original_answer": answer,
                }
            )

        save_csv(
            dataset_file,
            rows,
            ["id", "question", "original_answer"],
        )

        save_text(
            setting_file,
            f"Question:\n{question}\n\nNumber of examples:\n{n}\n",
        )

        st.success(f"Dataset saved: {dataset_file}")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with open(dataset_file, "rb") as f:
            st.download_button(
                "Download original dataset CSV",
                data=f,
                file_name=dataset_file.name,
                mime="text/csv",
            )


with tab_rewrite:
    st.subheader("Test rewrite prompt")

    dataset_files = list_csv_files(DATASET_DIR)

    uploaded_dataset = st.file_uploader(
        "Upload an existing original dataset CSV, or select one below",
        type=["csv"],
    )

    selected_file = None

    if uploaded_dataset is not None:
        dataset_df = pd.read_csv(uploaded_dataset)
        selected_dataset_name = uploaded_dataset.name
    else:
        if dataset_files:
            selected_path_str = st.selectbox(
                "Select existing dataset",
                options=[str(p) for p in dataset_files],
            )
            selected_file = Path(selected_path_str)
            dataset_df = load_dataset(selected_file)
            selected_dataset_name = selected_file.stem
        else:
            dataset_df = None
            selected_dataset_name = None
            st.info("No existing datasets found. Generate one first.")

    if dataset_df is not None:
        st.markdown("### Original dataset preview")
        st.dataframe(dataset_df, use_container_width=True, hide_index=True)

        rewrite_prompt = st.text_area(
            "Rewrite prompt to test",
            height=420,
            placeholder="Paste the exact prompt you want to test here. The code will not modify this prompt.",
        )

        prompt_version = st.text_input(
            "Prompt version name",
            placeholder="Example: v1_keep_gender_generalize_health",
        )

        if st.button("Run rewrite", type="primary"):
            required_cols = {"id", "question", "original_answer"}
            if not required_cols.issubset(set(dataset_df.columns)):
                st.error(
                    "Dataset must contain these columns: id, question, original_answer"
                )
                st.stop()

            if not rewrite_prompt.strip():
                st.warning("Please enter the rewrite prompt.")
                st.stop()

            if not prompt_version.strip():
                prompt_version = "prompt"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_folder = RESULT_DIR / f"{selected_dataset_name}_{prompt_version}_{timestamp}"
            run_folder.mkdir(parents=True, exist_ok=True)

            result_csv = run_folder / "rewrite_comparison.csv"
            prompt_txt = run_folder / "rewrite_prompt.txt"
            setting_txt = run_folder / "settings.txt"

            results = []
            progress = st.progress(0)

            for idx, row in dataset_df.iterrows():
                original_answer = str(row["original_answer"])

                with st.spinner(f"Rewriting example {idx + 1}/{len(dataset_df)}..."):
                    rewritten_answer = run_rewrite(original_answer, rewrite_prompt)

                results.append(
                    {
                        "id": row["id"],
                        "question": row["question"],
                        "original_answer": original_answer,
                        "rewritten_answer": rewritten_answer,
                        "prompt_version": prompt_version,
                    }
                )

                progress.progress((idx + 1) / len(dataset_df))

            save_csv(
                result_csv,
                results,
                [
                    "id",
                    "question",
                    "original_answer",
                    "rewritten_answer",
                    "prompt_version",
                ],
            )

            save_text(prompt_txt, rewrite_prompt)

            save_text(
                setting_txt,
                f"Dataset: {selected_dataset_name}\n"
                f"Prompt version: {prompt_version}\n"
                f"Model: {MODEL}\n"
                f"Time: {timestamp}\n",
            )

            result_df = pd.DataFrame(results)

            st.success("Rewrite finished.")
            st.markdown("### Rewrite comparison")
            st.dataframe(result_df, use_container_width=True, hide_index=True)

            col1, col2, col3 = st.columns(3)

            with col1:
                with open(result_csv, "rb") as f:
                    st.download_button(
                        "Download comparison CSV",
                        data=f,
                        file_name=result_csv.name,
                        mime="text/csv",
                    )

            with col2:
                with open(prompt_txt, "rb") as f:
                    st.download_button(
                        "Download prompt TXT",
                        data=f,
                        file_name=prompt_txt.name,
                        mime="text/plain",
                    )

            with col3:
                with open(setting_txt, "rb") as f:
                    st.download_button(
                        "Download settings TXT",
                        data=f,
                        file_name=setting_txt.name,
                        mime="text/plain",
                    )