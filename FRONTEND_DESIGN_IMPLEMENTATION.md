# Frontend Design Implementation

This document describes the vibrant design system implementation in the React frontend based on `design/design_reference.html`.

## Implementation Summary

The frontend design has been fully implemented with the following components and styling:

### ✅ Design System Files Created

1. **`src/styles/theme.css`** - Complete design token system
   - Color variables (page, surfaces, text, sentiment, accents)
   - Typography system (font families, sizes, weights)
   - Spacing scale (xs to 4xl)
   - Border radius scale (sm to xl)
   - Shadows and transitions
   - All component styling (cards, buttons, chips, charts, etc.)
   - Responsive breakpoints

### ✅ React Components Created

1. **`CatalystCard.jsx`** - Individual catalyst news card
   - Company avatar with dynamic gradient coloring
   - Company name and price with change percentage
   - Sentiment badge (strong/medium/neutral)
   - Headline text
   - 4-column stats bar (Vol vs avg, Day range, P/E, YTD)
   - Action buttons (View details, Track stock)
   - Color-coded left accent bar (hot/warm/neutral)

2. **`CatalystFeed.jsx`** - Catalyst feed container
   - Polls `/api/catalysts` endpoint every 60 seconds
   - Live indicator dot with pulsing animation
   - Last update time display
   - Filter chips (All, Earnings, Upgrades, M&A, FDA)
   - Consistent avatar color mapping per ticker
   - Loading and error states

3. **`StockDetail.jsx`** - Detailed stock view
   - Period tabs (1D, 5D, 1M, 3M, 6M, 1Y)
   - Chart.js line chart with gradient styling
   - Cyan → Green gradient line
   - Day trade metrics table
   - Long-term metrics table
   - Recent news list with sentiment scoring
   - Responsive metrics grid

4. **`ProviderStatusBadge.jsx`** - Provider health indicator
   - Fixed footer badge showing degraded providers
   - Fetches from `/api/health` endpoint
   - Only visible when providers are degraded
   - Updates every 30 seconds

5. **Updated `App.jsx`** - Main application component
   - Health check on app startup
   - Startup loading screen
   - Backend unavailable error screen
   - Catalyst feed integration
   - Stock detail modal
   - Provider status badge integration

### ✅ Styling Updates

1. **`App.css`** - App-level styling
   - Uses theme variables throughout
   - Vibrant dark navy background (#0F1419)
   - Health check screen styling
   - Modal animations

2. **`index.css`** - Global styling
   - Imports theme.css
   - Sets up body with theme variables
   - Input styling with focus states
   - Root element styling

## Design System Details

### Color Palette

| Variable | Value | Usage |
|----------|-------|-------|
| `--bg-page` | #0F1419 | Page background |
| `--bg-card` | #1A2030 | Card surfaces |
| `--bg-surface` | #232B3D | Nested surfaces |
| `--text-primary` | #F2F4F8 | Main text |
| `--text-secondary` | #9AA5BD | Secondary text |
| `--gain` | #10D982 | Bullish green |
| `--loss` | #FF5C5C | Bearish red |
| `--warm` | #F59E0B | Warning amber |
| `--accent-blue` | #3B82F6 | Primary accent |
| `--accent-purple` | #8B5CF6 | Secondary accent |
| `--accent-cyan` | #06B6D4 | Tertiary accent |

### Avatar Gradient Colors

- **Teal**: #10D982 → #06B6D4 (green to cyan)
- **Amber**: #F59E0B → #EF4444 (amber to red)
- **Purple**: #8B5CF6 → #EC4899 (purple to pink)
- **Blue**: #3B82F6 → #06B6D4 (blue to cyan)

### Sentiment Thresholds

| Score | Class | Badge | Bar Color |
|-------|-------|-------|-----------|
| ≥0.7 | hot | Green + Strong | Green→Cyan gradient |
| 0.3–0.7 | warm | Amber + Medium | Amber |
| <0.3 | neutral | Gray + Neutral | Blue |

### Spacing Scale

- `--space-xs`: 4px
- `--space-sm`: 8px
- `--space-md`: 12px
- `--space-lg`: 16px
- `--space-xl`: 20px
- `--space-2xl`: 24px
- `--space-3xl`: 32px
- `--space-4xl`: 48px

### Typography

- **Font Family**: -apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto
- **Base Sizes**: 11px (xs) to 26px (3xl)
- **Weights**: 400 (normal), 500 (medium), 600 (semibold), 700 (bold)

### Component Specifics

#### Catalyst Cards
- Left accent bar (3px) indicates sentiment level
- Hot cards: Green-to-cyan gradient bar with elevated styling
- Warm cards: Solid amber bar
- Neutral cards: Solid blue bar
- Hover state lifts card slightly and brightens background
- Stats bar uses nested surface with 4-column layout

#### Period Tabs
- Dark surface background with subtle borders
- Active tab has elevated background + soft shadow
- Smooth transitions on hover

#### Chart
- Line width: 2.5px with cyan→green gradient
- Fill area with 10% opacity green gradient
- No grid lines (clean sparkline look)
- Tooltip with dark background and light text
- Tabular-nums for price alignment

#### News List
- Left border (3px) indicates sentiment
- Strong: Green border
- Medium: Amber border
- Neutral: Gray border
- Hover state brightens background

## Backend Integration

The frontend expects the following API endpoints:

### `/api/health`
Returns provider health status:
```json
{
  "provider_status": {
    "finnhub": "ok|error|skipped",
    "alpha_vantage": "ok|error|skipped",
    "yfinance": "ok|error"
  }
}
```

### `/api/catalysts`
Query parameters: `lookback_hours`, `min_sentiment`, `limit`
Returns list of catalyst objects with sentiment scores

### `/api/stock/{symbol}/history`
Query parameters: `period` (1d, 5d, 1mo, 3mo, 6mo, 1y)
Returns OHLCV data by date

### `/api/stock/{symbol}/analysis`
Returns day_trade and long_term metrics

### `/api/stock/{symbol}/news`
Query parameters: `include_sentiment`
Returns news items with sentiment scores

## Running the Frontend

### Development
```bash
cd frontend
npm install  # if dependencies not installed
npm run dev
```
Frontend runs on `http://localhost:5173`

### Production Build
```bash
npm run build
npm run preview
```

## Responsive Design

- **Desktop (>640px)**: 2-column metrics grid, full spacing
- **Mobile (<640px)**: 1-column metrics grid, reduced padding, stacked layouts

## Browser Compatibility

- Modern browsers with ES6 support
- Chrome, Firefox, Safari, Edge (latest versions)
- Requires JavaScript enabled

## Notes

- All colors use CSS variables from theme.css for easy customization
- Animation transitions are smooth and performant (0.15s to 2s)
- Live dot indicator pulses with 2s ease-in-out animation
- Provider status badge only shows when issues are detected
- Health check runs on app startup and again every 30 seconds
- Catalyst feed polls every 60 seconds for fresh data
- All numeric values use `font-variant-numeric: tabular-nums` for alignment

## Design Decisions

1. **Dark Theme**: Vibrant dark navy (#0F1419) reduces eye strain while maintaining energy
2. **Gradient Accents**: Subtle gradients on primary CTAs create visual hierarchy
3. **Sentiment Colors**: Strong green (#10D982) for bullish signals, amber (#F59E0B) for medium signals
4. **Clean Sparklines**: Chart includes only data line and fill, no gridlines for minimal aesthetic
5. **Consistent Avatars**: Each ticker gets the same colored avatar for pattern recognition
6. **Left Accent Bar**: Card accent bar immediately communicates sentiment level before reading text
7. **Nested Surfaces**: Layered backgrounds create visual depth without heavy shadows

## Future Enhancements

- Dark/light theme toggle
- Custom color scheme selector
- Animated chart transitions
- Real-time WebSocket updates (instead of polling)
- Advanced filtering options
- Watchlist management UI
- Settings panel
