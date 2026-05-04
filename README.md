# MEP Tender Tracker

A professional portfolio prototype for monitoring, filtering, and analysing Mechanical, Electrical, and Plumbing (MEP) tenders in the UK public sector.

## Features

- **Automated Scaping:** Periodically fetches live tender data from the UK Contracts Finder API.
- **Smart Filtering:** Categorises tenders based on specific MEP keywords (HVAC, Electrical, Plumbing, etc.).
- **AI-Powered Summarisation:** Uses Google Gemini AI to generate concise technical summaries and strategic bid recommendations.
- **Bid Management:** Track the status of tenders (New, Under Review, Quoted, etc.) and manage internal quotes.
- **Modern Dashboard:** A clean, responsive interface built with Flask and Vanilla CSS.

## Tech Stack

- **Backend:** Python (Flask)
- **Database:** SQLite
- **AI Integration:** Google Gemini (Generative AI)
- **Frontend:** HTML5, Vanilla CSS, JavaScript
- **Deployment:** Ready for Heroku/Render via `Procfile`

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Goutamchandnani/MEP-Tender-Tracker.git
   cd MEP-Tender-Tracker
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root directory and add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

5. **Run the application:**
   ```bash
   python app.py
   ```
   The app will be available at `http://localhost:5050`.

## Project Structure

- `app.py`: Flask application server and API endpoints.
- `scraper.py`: Core logic for fetching and parsing data from Contracts Finder.
- `database.py`: SQLite schema and data persistence layer.
- `templates/index.html`: Main dashboard UI.
- `requirements.txt`: Project dependencies.

## Portfolio Note

This project was built to demonstrate full-stack development capabilities, API integration, and the practical application of AI in industry-specific automation tools. All company-specific branding has been removed for portfolio presentation.
