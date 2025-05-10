
import streamlit as st
import json
import requests
import tiktoken
import os
from dotenv import load_dotenv

st.set_page_config(page_title="Live Granite Log Summarizer", layout="wide")
st.title("Agentic Log Analyzer with Live Pipeline Flow + Chatbot")

# Load env vars
load_dotenv()

log_file = st.text_input("Path to Splunk JSONL log file", value="splunk_errorlog.jsonl")
model_id = st.text_input("Model ID", value="/data/granite-3.1-8b-instruct")
api_key = os.getenv("GRANITE_API_KEY_GRANITE_3_1_8b", "not_set")
st.write("API key loaded from environment.")
model_api = st.text_input("Granite API Endpoint", value="https://granite-3-1-8b-instruct--apicast-production.apps.int.stc.ai.prod.us-east-1.aws.paas.redhat.com:443")

MAX_TOKENS = 100000

def call_model(prompt, model_id, api_key, model_api):
    url = f"{model_api}/v1/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model_id,
        "prompt": prompt,
        "max_tokens": 750,
        "temperature": 0.3,
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            choices = response.json().get("choices", [])
            return choices[0].get("text", "").strip() if choices else "No response."
        else:
            st.error(f"API Error: {response.status_code} - {response.text}")
            return "Error in API call."
    except requests.RequestException as e:
        st.error(f"Request error: {e}")
        return "Error in API call."

def estimate_tokens(logs, encoding):
    total = 0
    for log in logs:
        total += len(encoding.encode(json.dumps(log)))
    return total

def load_and_parse_logs(path):
    logs = []
    with open(path, 'r') as file:
        for line in file:
            try:
                outer = json.loads(line)
                result = outer.get("result", {})
                raw = json.loads(result.get("_raw", "{}"))
                logs.append({
                    "_time": result.get("_time"),
                    "host": result.get("host"),
                    "message": raw.get("message"),
                    "spanId": raw.get("properties", {}).get("spanId"),
                    "traceId": raw.get("properties", {}).get("traceId"),
                    "source": result.get("source"),
                    "sourcetype": result.get("sourcetype")
                })
            except:
                continue
    return logs

def chunk_logs(logs, encoding, max_tokens=MAX_TOKENS):
    chunks = []
    current_chunk = []
    current_tokens = 0
    for log in logs:
        log_str = json.dumps(log)
        token_count = len(encoding.encode(log_str))
        if current_tokens + token_count > max_tokens:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0
        current_chunk.append(log)
        current_tokens += token_count
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

if st.button("Run Pipeline"):
    with st.status("Initializing...", expanded=True) as status:
        try:
            encoding = tiktoken.encoding_for_model(model_id)
        except:
            encoding = tiktoken.get_encoding("cl100k_base")

        status.update(label=":inbox_tray: Loading logs...")
        logs = load_and_parse_logs(log_file)
        st.success(f"Loaded {len(logs)} logs.")

        status.update(label=":1234: Estimating tokens...")
        total_tokens = estimate_tokens(logs, encoding)
        st.success(f"Estimated total tokens: {total_tokens}")

        status.update(label=":bricks: Chunking logs...")
        chunks = chunk_logs(logs, encoding)
        st.success(f"Created {len(chunks)} chunks.")

        summaries = []
        for i, chunk in enumerate(chunks):
            status.update(label=f":brain: Summarizing chunk {i+1}/{len(chunks)}...")
            formatted_logs = "\n".join([
                f"_time: {log.get('_time')}, host: {log.get('host')}, message: {log.get('message')}"
                for log in chunk
            ])
            prompt = f"""
You are an expert SRE assistant analyzing production error logs.
Group log entries into distinct error types. Summarize each group briefly.
Logs:
{formatted_logs}
"""
            summaries.append(call_model(prompt, model_id, api_key, model_api))

        status.update(label=":chart_with_upwards_trend: Synthesizing final summary...")
        final_prompt = "Combine the following summaries and highlight patterns, frequent errors, and affected services:\n" + "\n".join(summaries)
        final_summary = call_model(final_prompt, model_id, api_key, model_api)

        status.update(label=":white_check_mark: Pipeline complete", state="complete")
        st.session_state["log_summary"] = final_summary

    st.markdown("### Final Summary")
    st.text_area("Summary Output", value=final_summary, height=300)

    st.markdown("### Pipeline Flow")
    st.markdown(f"""
```mermaid
graph TD
    A[Load Logs ({len(logs)})] --> B[Token Estimate (~{total_tokens})]
    B --> C[Chunks ({len(chunks)})]
    C --> D[Granite Summary Per Chunk]
    D --> E[Final Summary]
```
""", unsafe_allow_html=True)

# Chat interface
st.markdown("---")
st.header("Chat with Summarized Logs")

if "log_summary" in st.session_state:
    with st.form("chat_form"):
        user_query = st.text_input("Ask a question about the logs:")
        submitted = st.form_submit_button("Ask")

    if submitted and user_query.strip():
        chat_prompt = f"""
You are a knowledgeable assistant. Use the following summary to answer questions:

Summary:
{st.session_state['log_summary']}

User Query:
{user_query}
"""
        chat_response = call_model(chat_prompt, model_id, api_key, model_api)
        st.markdown("**AI Response:**")
        st.write(chat_response)
else:
    st.info("Run the pipeline first to generate a summary before chatting.")
