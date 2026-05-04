import os
import json
import threading
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
from database import (
    init_db, get_all_tenders, get_tender, update_tender_status,
    save_ai_summary, add_quote, get_quotes_for_tender,
    get_all_quotes, update_quote_status, delete_quote,
    cleanup_expired_tenders
)
from scraper import scrape_all

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
ai_model = genai.GenerativeModel("gemini-2.5-flash")

app = Flask(__name__)
init_db()

# Global scrape state for async progress monitoring
_scrape_cancel = threading.Event()
_scrape_state = {
    "is_running": False,
    "current_keyword": "",
    "total_fetched": 0,
    "last_update": 0,
    "done": False
}

def _bg_scrape():
    """Background thread function for the scraper."""
    global _scrape_state
    _scrape_state["is_running"] = True
    _scrape_state["done"] = False
    _scrape_state["total_fetched"] = 0
    _scrape_state["last_update"] = 0
    
    def on_progress(kw, total, done):
        _scrape_state["current_keyword"] = kw
        _scrape_state["total_fetched"] = total
        _scrape_state["last_update"] = os.times().elapsed
        _scrape_state["done"] = done

    try:
        cleanup_expired_tenders() # Remove old clutter before fetching new ones
        scrape_all(save_to_db=True, cancel_event=_scrape_cancel, on_progress=on_progress)
    except Exception as e:
        print(f"[app] Scrape thread error: {e}")
    finally:
        _scrape_state["is_running"] = False
        _scrape_state["done"] = True


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API: Tenders ──────────────────────────────────────────────────────────────

@app.route("/api/tenders", methods=["GET"])
def api_tenders():
    keyword = request.args.get("keyword", "").strip()
    status  = request.args.get("status", "").strip()
    tenders = get_all_tenders(
        keyword=keyword or None,
        status=status or None,
    )
    return jsonify({"tenders": tenders, "count": len(tenders)})


@app.route("/api/tenders/<int:tender_id>", methods=["GET"])
def api_tender_detail(tender_id):
    t = get_tender(tender_id)
    if not t:
        return jsonify({"error": "Not found"}), 404
    t["quotes"] = get_quotes_for_tender(tender_id)
    return jsonify(t)


@app.route("/api/tenders/<int:tender_id>/status", methods=["POST"])
def api_update_status(tender_id):
    data   = request.get_json(force=True)
    status = data.get("status", "").strip()
    valid  = {"New", "Under Review", "Quoted", "Approved", "Lost"}
    if status not in valid:
        return jsonify({"error": f"Invalid status. Use one of: {valid}"}), 400
    update_tender_status(tender_id, status)
    return jsonify({"ok": True, "status": status})


@app.route("/api/tenders/<int:tender_id>/summarise", methods=["POST"])
def api_summarise(tender_id):
    t = get_tender(tender_id)
    if not t:
        return jsonify({"error": "Tender not found"}), 404

    # Return cached summary if already generated
    if t.get("ai_summary"):
        return jsonify({"summary": t["ai_summary"], "cached": True})

    prompt = f"""You are an expert bid analyst for a leading UK MEP contractor specialising in mechanical, electrical, and plumbing works.

Analyse the following UK public sector tender and provide a concise structured summary.

TENDER TITLE: {t['title']}
BUYER / CLIENT: {t['buyer']}
DEADLINE: {t['deadline']}
ESTIMATED VALUE: {t['value']}
LOCATION: {t['location']}
DESCRIPTION: {t['description']}

Provide your analysis in this exact format:

## What They Need
[2-3 sentences describing the scope of work]

## Key Details
- **Deadline:** {t['deadline']}
- **Value:** {t['value']}
- **Location:** {t['location']}

## Estimated Complexity
[Low / Medium / High] — [one sentence justification]

## MEP Relevance
[Briefly explain which specific technical disciplines—Mechanical, Electrical, or Plumbing—are most critical for this tender.]

## Strategic Recommendation
**[YES / NO / MAYBE]** — Frame your advice for a portfolio audience. Example: "If your firm specializes in [Specific Expertise, e.g., HVAC or Fire Systems], this is a [Strong/Moderate] match because [Reason]. This tender is ideal for contractors with a proven track record in [Specific Capability] and who are looking to work with [Buyer Type, e.g., Local Councils or NHS]."

"""

    try:
        response = ai_model.generate_content(prompt)
        summary  = response.text.strip()
        save_ai_summary(tender_id, summary)
        return jsonify({"summary": summary, "cached": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    if _scrape_state["is_running"]:
        return jsonify({"error": "Scrape already in progress"}), 400
    
    _scrape_cancel.clear()
    thread = threading.Thread(target=_bg_scrape)
    thread.daemon = True
    thread.start()
    
    return jsonify({"ok": True, "status": "started"})


@app.route("/api/scrape/status", methods=["GET"])
def api_scrape_status():
    return jsonify(_scrape_state)


@app.route("/api/scrape/stop", methods=["POST"])
def api_scrape_stop():
    _scrape_cancel.set()
    return jsonify({"ok": True, "message": "Stop signal sent"})


# ── API: Quotes ───────────────────────────────────────────────────────────────

@app.route("/api/quotes", methods=["GET"])
def api_all_quotes():
    return jsonify({"quotes": get_all_quotes()})


@app.route("/api/tenders/<int:tender_id>/quotes", methods=["GET"])
def api_tender_quotes(tender_id):
    return jsonify({"quotes": get_quotes_for_tender(tender_id)})


@app.route("/api/tenders/<int:tender_id>/quotes", methods=["POST"])
def api_add_quote(tender_id):
    data = request.get_json(force=True)
    quote_data = {
        "tender_id":       tender_id,
        "amount":          data.get("amount"),
        "submitted_date":  data.get("submitted_date", ""),
        "approval_status": data.get("approval_status", "Pending"),
        "notes":           data.get("notes", ""),
    }
    quote_id = add_quote(quote_data)
    return jsonify({"ok": True, "quote_id": quote_id})


@app.route("/api/quotes/<int:quote_id>/status", methods=["POST"])
def api_update_quote_status(quote_id):
    data   = request.get_json(force=True)
    status = data.get("status", "Pending")
    update_quote_status(quote_id, status)
    return jsonify({"ok": True})


@app.route("/api/quotes/<int:quote_id>", methods=["DELETE"])
def api_delete_quote(quote_id):
    delete_quote(quote_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
