# Frontend Design Quick Start

## Files Created/Updated

### New Components
- ✅ `src/components/CatalystCard.jsx` - Individual catalyst card
- ✅ `src/components/CatalystFeed.jsx` - Catalyst feed with polling
- ✅ `src/components/StockDetail.jsx` - Detailed stock view with chart
- ✅ `src/components/ProviderStatusBadge.jsx` - Provider health indicator

### New Styling
- ✅ `src/styles/theme.css` - Complete design system (1000+ lines)

### Updated Files
- ✅ `src/App.jsx` - Integrated new components and health check
- ✅ `src/App.css` - Updated with vibrant theme
- ✅ `src/index.css` - Imports theme system

## How to Use

### 1. Install dependencies (if not already done)
```bash
cd frontend
npm install
```

### 2. Ensure backend is running
```bash
cd backend
python main.py
# Should see: Uvicorn running on http://127.0.0.1:8000
```

### 3. Start frontend in development mode
```bash
cd frontend
npm run dev
```
Frontend will run on `http://localhost:5173`

### 4. Open in browser
Navigate to `http://localhost:5173` and you should see:
- **Loading screen** during health check
- **Error screen** if backend not responding
- **Catalyst feed** with live indicator if backend is healthy

## Visual Features

### 🎨 Vibrant Theme
- Dark navy background (#0F1419)
- Deep blue cards (#1A2030)
- Vivid sentiment colors (green #10D982, red #FF5C5C, amber #F59E0B)
- Gradient accents on buttons and avatars

### 📊 Catalyst Cards
- Color-coded sentiment indicators
- Company avatar with gradient background
- Price and change percentage
- 4-column metrics bar
- Action buttons (View details, Track stock)

### 📈 Stock Detail View
- Line chart with cyan→green gradient
- Period tabs (1D to 1Y)
- Day trade and long-term metrics
- Recent news with sentiment scores

### 🟢 Live Indicators
- Pulsing green dot when connected
- Grayed out when disconnected
- Last update time display
- Provider status badge (only when degraded)

## Component Architecture

```
App.jsx
├── CatalystFeed
│   ├── CatalystCard (repeated for each item)
│   │   ├── Avatar
│   │   ├── Company info
│   │   ├── Sentiment badge
│   │   ├── Stats bar
│   │   └── Action buttons
│   ├── Filter chips
│   └── Live indicator
├── StockDetail (shown when item clicked)
│   ├── Period tabs
│   ├── Chart
│   ├── Metrics grid
│   │   ├── Day trade table
│   │   └── Long-term table
│   └── News list
└── ProviderStatusBadge (footer, only if issues)
```

## API Integration Points

All components automatically fetch from these endpoints:

| Endpoint | Used By | Frequency |
|----------|---------|-----------|
| `/api/health` | App.jsx | On startup + 30s interval |
| `/api/catalysts` | CatalystFeed | On mount + 60s interval |
| `/api/stock/{symbol}/history` | StockDetail | On tab change |
| `/api/stock/{symbol}/analysis` | StockDetail | On mount |
| `/api/stock/{symbol}/news` | StockDetail | On mount |

## Styling System

All styling uses CSS variables defined in `src/styles/theme.css`:

```css
/* Colors */
--bg-page: #0F1419
--text-primary: #F2F4F8
--gain: #10D982
--warm: #F59E0B

/* Sizing */
--space-lg: 16px
--radius-lg: 14px

/* Typography */
--font-family: -apple-system, BlinkMacSystemFont, 'Inter', ...
--text-xl: 16px
--font-weight-semibold: 600

/* Other */
--transition-fast: 0.15s
--shadow-md: 0 4px 12px rgba(59, 130, 246, 0.3)
```

To customize the theme, edit values in `theme.css` and they'll automatically apply across all components.

## Responsive Design

- Desktop (>640px): Full layout with 2-column metrics
- Mobile (<640px): Stacked layout with 1-column metrics
- Reduces padding and adjusts spacing for smaller screens

## Testing the Components

### 1. Test Catalyst Feed
- Should show 3+ catalyst cards
- Click "View details" on any card
- Should switch to Stock Detail view

### 2. Test Stock Detail
- Should show period tabs and interactive chart
- Click period tabs to update chart
- Should display metrics tables
- Should show recent news items

### 3. Test Health Check
- Stop backend server
- Refresh page - should show "Backend unavailable"
- Restart backend
- Refresh page - should recover

### 4. Test Live Indicator
- Live dot should pulse (green)
- Stop backend for 10+ seconds
- Live dot should turn gray
- Restart backend
- Live dot should resume pulsing

## Common Issues & Fixes

### "Backend unavailable" error
**Solution**: Ensure backend is running
```bash
cd backend
python main.py
```

### Chart not showing data
**Solution**: Check `/api/stock/{symbol}/history` response in browser console
```bash
curl http://localhost:8000/api/stock/AAPL/history
```

### No catalyst cards showing
**Solution**: Check `/api/catalysts` response
```bash
curl http://localhost:8000/api/catalysts
```

### Styling looks wrong
**Solution**: Clear browser cache and reload
- Chrome: Ctrl+Shift+Delete (or Cmd+Shift+Delete on Mac)
- Firefox: Ctrl+Shift+Delete

## Next Steps

1. ✅ Frontend design implemented
2. ⏳ Backend needs multi-provider refactoring
3. ⏳ API endpoints need to be created/updated
4. ⏳ Testing suite needed
5. ⏳ Production build and deployment

See `FRONTEND_DESIGN_IMPLEMENTATION.md` for detailed design documentation.
