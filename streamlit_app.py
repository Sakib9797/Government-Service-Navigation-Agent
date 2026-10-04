"""
Streamlit UI for hosting on Streamlit Community Cloud. Same pipeline as app.py.

Run locally:  streamlit run streamlit_app.py
"""
import json
import os
import re
from datetime import datetime, timezone

import streamlit as st

from graph import answer

FEEDBACK = "data/feedback.jsonl"

EXAMPLES = [
    "আমার জমির খতিয়ান দরকার, কী করতে হবে?",
    "How do I renew my passport and how much does it cost?",
    "NID তে আমার নাম ভুল আছে, কীভাবে ঠিক করব?",
    "jonmo nibondhon korte koto taka lage",
    "TIN khulte koto taka lage",
]

# The composer folds the full record into <details>. Rendered as an expander
# instead, so st.markdown never needs unsafe_allow_html for model-written text.
DETAILS = re.compile(r"<details><summary>(.*?)</summary>(.*?)</details>", re.S)


def render(md):
    m = DETAILS.search(md)
    if not m:
        st.markdown(md)
        return
    st.markdown(md[:m.start()])
    with st.expander(m.group(1).strip()):
        st.markdown(m.group(2))
    if md[m.end():].strip():
        st.markdown(md[m.end():])


def report(query, answer_text, note):
    """Written to disk for HUMAN review only; never fed back into the index."""
    os.makedirs("data", exist_ok=True)
    with open(FEEDBACK, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            "query": query, "note": note, "answer_excerpt": (answer_text or "")[:500],
            "status": "unreviewed",
        }, ensure_ascii=False) + "\n")


def use_example(q):
    st.session_state.query = q
    st.session_state.pending = True


st.set_page_config(page_title="সরকারি সেবা সহায়ক / Govt Service Navigator", page_icon="🇧🇩")

st.title("🇧🇩 সরকারি সেবা সহায়ক")
st.subheader("Government Service Navigation Agent")
st.markdown(
    "বাংলা বা English — যেকোনো ভাবে প্রশ্ন করুন। / Ask in Bengali, English, or a mix.\n\n"
    "> সব তথ্যের সাথে উৎস ও তারিখ দেওয়া হয়। কাজ করার আগে অবশ্যই যাচাই করুন।  \n"
    "> Every answer carries its source and date. Always verify before acting."
)

with st.form("ask"):
    st.text_area("আপনার প্রশ্ন / Your question", key="query", height=80,
                 placeholder="যেমন: পাসপোর্ট নবায়ন করতে কী কী লাগে?")
    submitted = st.form_submit_button("জিজ্ঞাসা করুন / Ask", type="primary")

st.caption("Examples")
for i, ex in enumerate(EXAMPLES):
    st.button(ex, key=f"ex{i}", on_click=use_example, args=(ex,))

if submitted or st.session_state.pop("pending", False):
    q = (st.session_state.get("query") or "").strip()
    if not q:
        st.warning("প্রশ্ন লিখুন / Please type a question.")
    else:
        with st.spinner("উত্তর খোঁজা হচ্ছে… / Finding the answer… "
                        "(the first question after the app wakes up can take a minute)"):
            out = answer(q)
        st.session_state.result = (q, out["answer"], "\n".join(f"- {t}" for t in out.get("trace", [])))

if "result" in st.session_state:
    q, md, trace = st.session_state.result
    st.divider()
    render(md)
    with st.expander("🔍 Pipeline trace (how this answer was produced)"):
        st.markdown(trace)

with st.expander("⚠️ ভুল তথ্য জানান / Report incorrect information"):
    st.markdown("_সরকারি তথ্য পরিবর্তন হয়। ভুল দেখলে জানান — যাচাই করে ঠিক করা হবে।_")
    with st.form("report", clear_on_submit=True):
        note = st.text_area("কী ভুল? / What was wrong?")
        if st.form_submit_button("রিপোর্ট পাঠান / Submit report"):
            q, md, _ = st.session_state.get("result", ("", "", ""))
            if q or note:
                report(q, md, note)
                st.success("ধন্যবাদ! রিপোর্টটি জমা হয়েছে, যাচাইয়ের পর সংশোধন করা হবে। / "
                           "Thanks - logged for human review.")
            else:
                st.info("Nothing to report.")
