import io
import sys
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from PIL import Image

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import settings
from pipeline.document_loader import load_document
from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output
from eval.harness import run_evaluation
from ai_backends.router import get_backend

st.set_page_config(
    page_title="EsMagico Invoice Intelligence",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom minimal business CSS
st.markdown("""
<style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    h1, h2, h3 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-weight: 600; }
    .stMetric { background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 12px; }
    .badge-valid { color: #155724; background-color: #d4edda; border: 1px solid #c3e6cb; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .badge-review { color: #856404; background-color: #fff3cd; border: 1px solid #ffeeba; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("🧾 EsMagico AI")
    st.caption("Intelligent Invoice Extraction Pipeline")
    st.divider()

    st.subheader("Runtime Configuration")
    active_mode = st.selectbox(
        "Default AI Backend",
        options=["no_ai", "groq", "local", "gemini", "openai", "antigravity"],
        index=["no_ai", "groq", "local", "gemini", "openai", "antigravity"].index(
            settings.ai_mode if settings.ai_mode in ["no_ai", "groq", "local", "gemini", "openai", "antigravity"] else "no_ai"
        )
    )

    groq_keys_count = len(settings.groq_api_keys)
    st.metric("Groq Key Pool", f"{groq_keys_count} keys active")
    st.metric("Tolerance", f"±{settings.arithmetic_tolerance:.2f}")
    st.divider()
    st.caption("AI Intern Assignment | Production Architecture")

# Tabs
tab_extract, tab_batch, tab_eval, tab_cost, tab_config = st.tabs([
    "🔍 Document Extraction",
    "📁 Batch Runner",
    "📊 Evaluation Harness",
    "💰 Cost & Market ROI",
    "⚙️ Configuration"
])

# -------------------------------------------------------------
# TAB 1: SINGLE DOCUMENT EXTRACTION
# -------------------------------------------------------------
with tab_extract:
    st.header("Invoice Extraction & Verification")
    st.write("Upload any PDF, scan, or phone image, or choose from the sample pack.")

    col_input, col_output = st.columns([1, 1], gap="medium")

    with col_input:
        st.subheader("Document Input")
        source_type = st.radio("Input Source", ["Sample Pack File", "Upload Custom File"], horizontal=True)

        selected_file_path: Path = None

        if source_type == "Sample Pack File":
            labelled_p = settings.resolve_path(settings.labelled_dir)
            unlabelled_p = settings.resolve_path(settings.unlabelled_dir)

            sample_files = []
            if labelled_p.exists():
                sample_files.extend(list(labelled_p.glob("L*.*")))
            if unlabelled_p.exists():
                sample_files.extend(list(unlabelled_p.glob("U*.*")))

            sample_files = [f for f in sorted(sample_files) if f.suffix.lower() != ".json"]
            file_options = {f"{f.parent.name} / {f.name}": f for f in sample_files}

            if file_options:
                chosen_label = st.selectbox("Select Sample Document", list(file_options.keys()))
                selected_file_path = file_options[chosen_label]
        else:
            uploaded = st.file_uploader("Upload Document (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"])
            if uploaded:
                temp_p = BASE_DIR / "temp_upload" / uploaded.name
                temp_p.parent.mkdir(exist_ok=True)
                with open(temp_p, "wb") as f:
                    f.write(uploaded.getbuffer())
                selected_file_path = temp_p

        extract_btn = st.button("🚀 Extract & Validate", type="primary", use_container_width=True)

        if selected_file_path and selected_file_path.exists():
            st.divider()
            doc_preview = load_document(selected_file_path)
            st.caption(f"Previewing: `{selected_file_path.name}` ({doc_preview.page_count} pages)")
            if doc_preview.images:
                st.image(doc_preview.images[0], use_column_width=True)

    with col_output:
        st.subheader("Structured Extraction Output")

        if extract_btn and selected_file_path:
            with st.spinner(f"Extracting with {active_mode}..."):
                backend = get_backend(active_mode)
                extractor = InvoiceExtractor(backend)
                res = extractor.extract(selected_file_path)
                st.session_state["latest_result"] = res

        if "latest_result" in st.session_state:
            res = st.session_state["latest_result"]
            pred = res.data or {}

            # Verification Status Badge
            if res.error:
                st.error(f"Extraction Error: {res.error}")
            elif res.needs_review:
                st.warning(f"⚠️ Validation Flag: {', '.join(res.review_reasons)}")
            else:
                st.success("✅ Output Verified: Schema Valid & Totals Balanced")

            # High-level metrics
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Is Invoice", "Yes" if pred.get("is_invoice") else "No")
            c2.metric("Currency", pred.get("currency") or "—")
            c3.metric("Tax Total", f"{pred.get('tax_total'):.2f}" if pred.get("tax_total") is not None else "—")
            c4.metric("Total Due", f"{pred.get('total'):.2f}" if pred.get("total") is not None else "—")

            # Formatted Line Items
            items = pred.get("line_items")
            if items:
                st.markdown("**Extracted Line Items:**")
                df_items = pd.DataFrame(items)
                st.dataframe(df_items, use_container_width=True)

            # Raw JSON Output
            with st.expander("View Full JSON Payload", expanded=True):
                st.json(pred)

            # Download button
            json_str = json.dumps(pred, indent=2)
            st.download_button(
                label="⬇️ Download JSON",
                data=json_str,
                file_name=f"{selected_file_path.stem}.json" if selected_file_path else "extracted.json",
                mime="application/json"
            )

# -------------------------------------------------------------
# TAB 2: BATCH RUNNER
# -------------------------------------------------------------
with tab_batch:
    st.header("Batch Processing Engine")
    st.write("Process all documents in a selected folder sequentially and export structured JSONs.")

    col_b1, col_b2 = st.columns([2, 1])
    with col_b1:
        batch_folder = st.selectbox(
            "Select Target Dataset",
            ["Labelled Documents (L01 - L10)", "Unlabelled Documents (U01 - U10)"]
        )
    with col_b2:
        batch_mode = st.selectbox("AI Backend for Batch", ["no_ai", "groq", "local", "gemini", "openai"], index=0)

    start_batch = st.button("⚡ Run Batch Extraction", type="primary")

    if start_batch:
        target_dir = settings.resolve_path(settings.labelled_dir if "Labelled" in batch_folder else settings.unlabelled_dir)
        extensions = ("*.pdf", "*.jpg", "*.jpeg", "*.png")
        files = []
        for ext in extensions:
            files.extend(list(target_dir.glob(ext)))
        files = sorted(set(files))

        backend = get_backend(batch_mode)
        extractor = InvoiceExtractor(backend)

        results_list = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, f in enumerate(files):
            status_text.text(f"Processing ({idx+1}/{len(files)}): {f.name}")
            r = extractor.extract(f)
            pred = r.data or {}
            write_output(f.stem, pred)

            results_list.append({
                "File": f.name,
                "Is Invoice": "Yes" if pred.get("is_invoice") else "No",
                "Vendor": pred.get("vendor"),
                "Invoice #": pred.get("invoice_number"),
                "Date": pred.get("invoice_date"),
                "Currency": pred.get("currency"),
                "Total": pred.get("total"),
                "Status": "Needs Review" if r.needs_review else ("Error" if r.error else "Valid")
            })
            progress_bar.progress((idx + 1) / len(files))

        status_text.text(f"Completed processing {len(files)} documents!")
        st.dataframe(pd.DataFrame(results_list), use_container_width=True)

# -------------------------------------------------------------
# TAB 3: EVALUATION HARNESS
# -------------------------------------------------------------
with tab_eval:
    st.header("Evaluation Harness & Accuracy Benchmarking")
    st.write("Compare model predictions field-by-field against ground truth answers in `labelled/`.")

    col_e1, col_e2 = st.columns([2, 1])
    with col_e1:
        st.write("Matching rules applied: exact boolean, fuzzy vendor (>=85%), exact dates & currency, table items ±0.05 tolerance.")
    with col_e2:
        eval_run_btn = st.button("📊 Run Evaluation on L01..L10", type="primary", use_container_width=True)

    if eval_run_btn:
        with st.spinner(f"Evaluating {active_mode} on 10 labelled documents..."):
            summary = run_evaluation(mode=active_mode)
            st.session_state["eval_summary"] = summary

    if "eval_summary" in st.session_state:
        s = st.session_state["eval_summary"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Overall Accuracy", f"{s.overall_accuracy:.1f}%")
        m2.metric("Evaluated Docs", str(s.total_docs))
        m3.metric("Tokens Consumed", f"{s.total_tokens_in + s.total_tokens_out:,}")
        m4.metric("Total Run Cost", f"${s.total_cost_usd:.6f}")

        st.subheader("Field-Level Accuracy Breakdown")
        df_acc = pd.DataFrame([
            {"Field": f, "Accuracy (%)": acc, "Correct": s.field_correct_counts[f], "Total": s.total_docs}
            for f, acc in s.field_accuracy.items()
        ])
        st.dataframe(df_acc, use_container_width=True)

        st.bar_chart(df_acc.set_index("Field")["Accuracy (%)"])

        st.subheader("Per-Document Field Matrix")
        matrix_rows = []
        for rec in s.document_records:
            row = {"Doc ID": rec.doc_id, "File": rec.file_name}
            for f, val in rec.field_matches.items():
                row[f] = "✅" if val else "❌"
            matrix_rows.append(row)
        st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True)

# -------------------------------------------------------------
# TAB 4: COST & MARKET ROI
# -------------------------------------------------------------
with tab_cost:
    st.header("Cost Analysis & Market Intelligence")

    st.subheader("Real Cost per Document Across Solutions")
    cost_data = [
        {"Provider / Solution": "Manual Data Entry (Human AP Clerk)", "Cost per Invoice": "$12.00 - $18.00", "Monthly (500 Invoices)": "$6,000 - $9,000", "Annual (6,000 Invoices)": "$72,000 - $108,000"},
        {"Provider / Solution": "Enterprise IDP (Rossum, ABBYY)", "Cost per Invoice": "$0.20 - $0.60+", "Monthly (500 Invoices)": "$100 - $300+", "Annual (6,000 Invoices)": "$15,000+ base contract"},
        {"Provider / Solution": "Developer IDP (Nanonets, Mindee)", "Cost per Invoice": "$0.05 - $0.15", "Monthly (500 Invoices)": "$25 - $75", "Annual (6,000 Invoices)": "$1,200+ (subscription)"},
        {"Provider / Solution": "Hyperscale Cloud (AWS Textract, Google DocAI)", "Cost per Invoice": "$0.015 - $0.025", "Monthly (500 Invoices)": "$7.50 - $12.50", "Annual (6,000 Invoices)": "$90.00 - $150.00"},
        {"Provider / Solution": "This Pipeline: OpenAI GPT-4o-mini", "Cost per Invoice": "~$0.0006", "Monthly (500 Invoices)": "$0.30", "Annual (6,000 Invoices)": "$3.60"},
        {"Provider / Solution": "This Pipeline: Groq Free Tier (10-key rotation)", "Cost per Invoice": "$0.0000", "Monthly (500 Invoices)": "$0.00", "Annual (6,000 Invoices)": "$0.00"},
        {"Provider / Solution": "This Pipeline: No-AI Rule Engine / Local LLM", "Cost per Invoice": "$0.0000", "Monthly (500 Invoices)": "$0.00", "Annual (6,000 Invoices)": "$0.00"},
    ]
    st.dataframe(pd.DataFrame(cost_data), use_container_width=True)

    st.subheader("Client ROI Calculator")
    invoices_per_month = st.slider("Monthly Invoice Volume", min_value=100, max_value=20000, value=500, step=100)
    current_cost_per_doc = st.number_input("Current Estimated Manual Cost per Invoice (USD)", value=15.0, min_value=1.0)

    manual_annual = invoices_per_month * current_cost_per_doc * 12
    pipeline_annual = invoices_per_month * 0.0006 * 12
    savings = manual_annual - pipeline_annual

    r1, r2, r3 = st.columns(3)
    r1.metric("Current Manual Annual Expense", f"${manual_annual:,.2f}")
    r2.metric("Pipeline Annual Expense", f"${pipeline_annual:,.2f}")
    r3.metric("Projected Annual Net Savings", f"${savings:,.2f}")

# -------------------------------------------------------------
# TAB 5: CONFIGURATION
# -------------------------------------------------------------
with tab_config:
    st.header("Pipeline Configuration Details")
    st.json({
        "AI_MODE": settings.ai_mode,
        "GROQ_KEYS_LOADED": len(settings.groq_api_keys),
        "GROQ_VISION_MODEL": settings.groq_vision_model,
        "GROQ_TEXT_MODEL": settings.groq_text_model,
        "LOCAL_LLM_URL": settings.local_llm_base_url,
        "LOCAL_LLM_MODEL": settings.local_llm_model,
        "ARITHMETIC_TOLERANCE": settings.arithmetic_tolerance,
        "LABELLED_PATH": str(settings.resolve_path(settings.labelled_dir)),
        "UNLABELLED_PATH": str(settings.resolve_path(settings.unlabelled_dir)),
        "OUTPUTS_PATH": str(settings.resolve_path(settings.outputs_dir)),
    })
