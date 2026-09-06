"""
Bengali-first chat UI for the Government Service Navigation Agent.

explain.md Phase 4: Bengali-first interface plus a "report incorrect info"
feedback loop, because government data drifts and citizens notice before any
re-scrape does.

Run:  python app.py        then open the printed local URL
"""
import json
import os
from datetime import datetime, timezone

import os

# Gradio phones home to api.gradio.app with usage telemetry by default.
# For a citizen-facing government tool that must not happen: queries here are
# things like "my child's birth was never registered". Off before import.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr

from graph import answer

FEEDBACK = "data/feedback.jsonl"

EXAMPLES = [
    "আমার জমির খতিয়ান দরকার, কী করতে হবে?",
    "How do I renew my passport and how much does it cost?",
    "NID তে আমার নাম ভুল আছে, কীভাবে ঠিক করব?",
    "jonmo nibondhon korte koto taka lage",
    "TIN khulte koto taka lage",
]


def ask(query):
    if not query or not query.strip():
        return "প্রশ্ন লিখুন / Please type a question.", ""
    out = answer(query.strip())
    trace = "\n".join(f"- {t}" for t in out.get("trace", []))
    return out["answer"], trace


def report(query, answer_text, note):
    """Crowdsourced correction loop. Written to disk for HUMAN review only.

    Nothing here re-enters the RAG index automatically: explain.md is explicit
    that community reports must be manually verified before inclusion.
    """
    if not (query or note):
        return "Nothing to report."
    os.makedirs("data", exist_ok=True)
    with open(FEEDBACK, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            "query": query, "note": note, "answer_excerpt": (answer_text or "")[:500],
            "status": "unreviewed",
        }, ensure_ascii=False) + "\n")
    return "ধন্যবাদ! রিপোর্টটি জমা হয়েছে, যাচাইয়ের পর সংশোধন করা হবে। / Thanks - logged for human review."


with gr.Blocks(title="সরকারি সেবা সহায়ক / Govt Service Navigator", analytics_enabled=False) as demo:
    gr.Markdown(
        "# 🇧🇩 সরকারি সেবা সহায়ক\n"
        "### Government Service Navigation Agent\n"
        "বাংলা বা English — যেকোনো ভাবে প্রশ্ন করুন। / Ask in Bengali, English, or a mix.\n\n"
        "> সব তথ্যের সাথে উৎস ও তারিখ দেওয়া হয়। কাজ করার আগে অবশ্যই যাচাই করুন।\n"
        "> Every answer carries its source and date. Always verify before acting."
    )
    with gr.Row():
        q = gr.Textbox(label="আপনার প্রশ্ন / Your question", lines=2, scale=4,
                       placeholder="যেমন: পাসপোর্ট নবায়ন করতে কী কী লাগে?")
        btn = gr.Button("জিজ্ঞাসা করুন / Ask", variant="primary", scale=1)
    gr.Examples(EXAMPLES, inputs=q)
    out = gr.Markdown(label="উত্তর / Answer")
    with gr.Accordion("🔍 Pipeline trace (how this answer was produced)", open=False):
        tr = gr.Markdown()
    with gr.Accordion("⚠️ ভুল তথ্য জানান / Report incorrect information", open=False):
        gr.Markdown("_সরকারি তথ্য পরিবর্তন হয়। ভুল দেখলে জানান — যাচাই করে ঠিক করা হবে।_")
        note = gr.Textbox(label="কী ভুল? / What was wrong?", lines=2)
        rbtn = gr.Button("রিপোর্ট পাঠান / Submit report")
        rout = gr.Markdown()

    btn.click(ask, [q], [out, tr])
    q.submit(ask, [q], [out, tr])
    rbtn.click(report, [q, out, note], [rout])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
