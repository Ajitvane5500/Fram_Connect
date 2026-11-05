# FarmConnect – Smart Farming Guidance Platform

FarmConnect is a starter Flask web application that connects farmers with visitors who want to learn about farming. It includes farmer profiles, location/crop search, visit booking requests, basic crop guidance, and an admin dashboard.

## Features
- Farmer registration and profile listing
- Search farmers by name, village, district, or crop
- Visitor farm-visit booking request
- Basic crop guidance information
- Admin dashboard to view farmers and update booking status
- SQLite database created automatically

## Run locally
1. Install Python 3.10 or newer.
2. Open this folder in VS Code.
3. Create and activate a virtual environment:
   - Windows: `py -m venv venv` then `venv\\Scripts\\activate`
   - macOS/Linux: `python3 -m venv venv` then `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Start the app: `python app.py`
6. Open `http://127.0.0.1:5000`

## Deploy on Render
- Push this folder to a GitHub repository.
- Create a new **Web Service** on Render and connect the repository.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Runtime: Python 3.
- Note: SQLite on many hosted free instances may not be persistent across redeploys/restarts. For a real deployment, use a managed PostgreSQL database and configure a persistent database connection.

## Important limitations / next development steps
- This is a working academic prototype, not a production marketplace.
- Payment is NOT processed. The booking page clearly states that payment is not collected. Integrate a legitimate payment gateway (such as Razorpay) only after creating a merchant account and implementing server-side verification/webhooks.
- The crop guidance is general educational information, not a pesticide prescription. Before recommending any pesticide/fertilizer, verify the crop, pest/disease, label-approved dosage, local regulations, protective equipment, and pre-harvest interval with a qualified agricultural officer/KVK.
- The crop disease AI feature is planned but not implemented in this starter version. It needs a labelled dataset, trained model, validation, and a safe uncertainty-aware interface.
- The `/admin` page is a demonstration page and has no login protection. Add authentication and role-based access before public deployment.
- Add OTP verification, privacy notice, consent, input validation, rate limiting, HTTPS, backups, and secure secret management before production use.
