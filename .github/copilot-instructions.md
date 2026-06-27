# GitHub Copilot Custom Instructions for Stock Market Dashboard

## Project Overview
This is a full-stack stock market dashboard application:
- **Backend**: FastAPI (Python) with yfinance for Yahoo Finance data
- **Frontend**: React + Vite with Chart.js for visualizations
- **Purpose**: Real-time stock tracking with KPIs and price history charts

## Key File Locations
- Backend: `/backend/main.py` (FastAPI app)
- Backend dependencies: `/backend/requirements.txt`
- Frontend: `/frontend/src/` (React components)
- Frontend config: `/frontend/vite.config.js`, `/frontend/package.json`

## Development Tasks Completed
- [x] Create copilot-instructions.md file
- [x] Scaffold backend and frontend structure
- [x] Create backend dependencies (requirements.txt)
- [x] Create frontend dependencies (package.json)
- [x] Implement FastAPI application with stock data routes
- [x] Implement React dashboard with stock cards and charts
- [x] Create comprehensive README with setup instructions

## Getting Started

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
python main.py
```
Backend runs on `http://localhost:8000`

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Frontend runs on `http://localhost:5173`

## API Endpoints
- `GET /api/stock/{symbol}` - Stock information
- `GET /api/stock/{symbol}/history` - Historical prices
- `GET /api/search/{query}` - Stock search
- `GET /api/health` - Health check
- `GET /docs` - Swagger API docs

## Frontend Components
- `App.jsx` - Main application component
- `StockSearch.jsx` - Search form component
- `StockCard.jsx` - Individual stock display card
- `StockChart.jsx` - Price history chart component

## Next Steps
1. Install dependencies in both backend and frontend
2. Run both servers in separate terminals
3. Open `http://localhost:5173` in browser
4. Search for stock symbols to test functionality
5. Customize as needed (add more KPIs, features, styling)

## Common Commands
- Backend: `python main.py` or `uvicorn main:app --reload`
- Frontend: `npm run dev` (dev), `npm run build` (production)
- API Docs: `http://localhost:8000/docs`

## Notes
- CORS configured for `localhost:5173` and `localhost:3000`
- Requires active internet connection to fetch Yahoo Finance data
- Uses Python 3.9+ and Node.js 16+
