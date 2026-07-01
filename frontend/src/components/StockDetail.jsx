import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../api';
import axios from 'axios';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
} from 'chart.js';
import '../styles/theme.css';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler
);

/**
 * StockDetail - Shows detailed view of a stock with chart and metrics
 * Includes period tabs (1D, 5D, 1M, 3M, 6M, 1Y), chart, and dual metrics sections
 */
const METRIC_TOOLTIPS = {
  price: "Current trading price per share. Example: $283.78 means each share costs $283.78 right now.",
  open: "Price at which the stock started trading today. Example: $275.00 was today's opening price.",
  dayHL: "Highest and lowest price reached today. Example: $286 high / $274 low is a $12 trading range.",
  prevClose: "Closing price from the previous trading session. Example: $275.15 was yesterday's close.",
  intraday: "Percent change from today's open to the current price. Example: +3.14% means the price rose 3.14% since opening.",
  volAvg: "Today's volume vs the average recent volume. Example: 261M vs 64M avg means much higher trading activity than usual.",
  pe: "Price-to-earnings ratio: share price divided by earnings per share. Example: P/E of 34 means investors pay $34 per $1 of earnings.",
  marketCap: "Total value of all outstanding shares (price x shares outstanding). Example: $4.17T means the company is worth $4.17 trillion.",
  range52w: "Lowest and highest price over the past 52 weeks. Example: $199 - $317 shows the year's trading range.",
  divYield: "Annual dividend payments as a percent of share price. Example: 0.38% yield pays $0.38/year per $100 invested.",
  analystTarget: "Average 12-month price target from Wall Street analysts. Example: $315 target means analysts expect the price to reach $315.",
  ytd: "Percent change in price since the start of the year. Example: +4.42% means the stock has gained 4.42% year-to-date.",
};

const LabelWithTooltip = ({ label, tooltip }) => (
  <span className="label-tooltip">
    {label}
    <span className="tooltip-box">{tooltip}</span>
  </span>
);

const StockDetail = ({ symbol, onClose }) => {
  const [period, setPeriod] = useState('5D');
  const [chartData, setChartData] = useState(null);
  const [dayMetrics, setDayMetrics] = useState(null);
  const [longTermMetrics, setLongTermMetrics] = useState(null);
  const [news, setNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const chartRef = useRef(null);

  const periods = ['1D', '5D', '1M', '3M', '6M', '1Y'];
  const periodToDays = {
    '1D': '1d',
    '5D': '5d',
    '1M': '1mo',
    '3M': '3mo',
    '6M': '6mo',
    '1Y': '1y',
  };

  // Fetch chart data and metrics
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);

        // Fetch historical price data
        const historyResponse = await axios.get(
          `${API_BASE_URL}/stock/${symbol}/history`,
          {
            params: { period: periodToDays[period] },
          }
        );

        // Fetch analysis (day trade + long term metrics)
        const analysisResponse = await axios.get(
          `${API_BASE_URL}/stock/${symbol}/analysis`
        );

        // Fetch news
        const newsResponse = await axios.get(
          `${API_BASE_URL}/stock/${symbol}/news`,
          {
            params: { include_sentiment: true },
          }
        );

        // Process chart data
        if (historyResponse.data?.data) {
          const prices = historyResponse.data.data;
          const dates = Object.keys(prices).sort();
          const chartPrices = dates.map((date) => prices[date].close);

          setChartData({
            labels: dates.map((date) => new Date(date).toLocaleDateString()),
            prices: chartPrices,
          });
        }

        // Process metrics
        if (analysisResponse.data?.data) {
          const analysis = analysisResponse.data.data;
          setDayMetrics(analysis.day_trade);
          setLongTermMetrics(analysis.long_term);
        }

        // Process news
        if (newsResponse.data?.data) {
          setNews(newsResponse.data.data.slice(0, 4));
        }
      } catch (error) {
        console.error('Error fetching stock details:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [symbol, period]);

  // Generate chart configuration
  const getChartConfig = () => {
    if (!chartData?.prices || chartData.prices.length === 0) {
      return null;
    }

    const prices = chartData.prices;
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);

    return {
      labels: chartData.labels,
      datasets: [
        {
          label: symbol,
          data: prices,
          borderColor: 'url(#chartGradient)',
          backgroundColor: 'rgba(16, 217, 130, 0.1)',
          fill: true,
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.4,
          borderJoinStyle: 'round',
        },
      ],
    };
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      intersect: false,
      mode: 'index',
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: 'rgba(15, 20, 25, 0.9)',
        borderColor: 'rgba(255, 255, 255, 0.12)',
        borderWidth: 1,
        padding: 12,
        titleColor: '#F2F4F8',
        bodyColor: '#9AA5BD',
        bodyFont: {
          size: 13,
        },
        titleFont: {
          size: 14,
          weight: 600,
        },
        displayColors: false,
        callbacks: {
          label: (context) => {
            return `$${context.parsed.y.toFixed(2)}`;
          },
        },
      },
    },
    scales: {
      x: {
        display: true,
        grid: {
          display: false,
          color: 'transparent',
        },
        ticks: {
          color: '#6B7593',
          font: {
            size: 11,
          },
          maxTicksLimit: 6,
        },
      },
      y: {
        display: true,
        grid: {
          color: 'rgba(255, 255, 255, 0.06)',
          drawBorder: false,
        },
        ticks: {
          color: '#6B7593',
          font: {
            size: 11,
          },
          callback: (value) => `$${value.toFixed(0)}`,
        },
      },
    },
  };

  // Determine sentiment class for news items
  const getSentimentClass = (sentiment) => {
    if (sentiment >= 0.7) return 'strong';
    if (sentiment >= 0.3) return 'medium';
    return 'neutral';
  };

  const config = getChartConfig();

  return (
    <div className="stock-detail-modal">
      <div className="detail-card">
        {/* Header with close button */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div>
            <h2>Stock Details — {symbol}</h2>
          </div>
          {onClose && (
            <button className="btn" onClick={onClose} style={{ width: 'auto' }}>
              Close
            </button>
          )}
        </div>

        {/* Period tabs */}
        <div className="period-tabs">
          {periods.map((p) => (
            <span
              key={p}
              className={`period-tab ${p === period ? 'active' : ''}`}
              onClick={() => setPeriod(p)}
            >
              {p}
            </span>
          ))}
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-secondary)' }}>
            Loading chart data...
          </div>
        ) : (
          <>
            {/* Chart */}
            {config && (
              <div className="chart-wrap">
                <Line ref={chartRef} data={config} options={chartOptions} />
              </div>
            )}

            {/* Metrics Grid */}
            <div className="metrics-grid">
              {/* Day Trade View */}
              <div>
                <p className="metrics-section-title">
                  <span className="dot day" />
                  Day trade view
                </p>
                <div className="metrics-table-wrap">
                  <table className="metrics-table">
                    <tbody>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Price" tooltip={METRIC_TOOLTIPS.price} /></td>
                        <td className="value bold">${dayMetrics?.price?.toFixed(2)}</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Open" tooltip={METRIC_TOOLTIPS.open} /></td>
                        <td className="value">${dayMetrics?.open?.toFixed(2)}</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Day H/L" tooltip={METRIC_TOOLTIPS.dayHL} /></td>
                        <td className="value">
                          ${dayMetrics?.day_high?.toFixed(0)} / ${dayMetrics?.day_low?.toFixed(0)}
                        </td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Prev close" tooltip={METRIC_TOOLTIPS.prevClose} /></td>
                        <td className="value">${dayMetrics?.previous_close?.toFixed(2)}</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Intraday %" tooltip={METRIC_TOOLTIPS.intraday} /></td>
                        <td className={`value bold ${dayMetrics?.change_percent >= 0 ? 'up' : 'down'}`}>
                          {dayMetrics?.change_percent >= 0 ? '+' : ''}{dayMetrics?.change_percent?.toFixed(2)}%
                        </td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Vol / avg" tooltip={METRIC_TOOLTIPS.volAvg} /></td>
                        <td className="value">
                          {(dayMetrics?.volume / 1000000)?.toFixed(0)}M / {(dayMetrics?.avg_volume / 1000000)?.toFixed(0)}M
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Long-term View */}
              <div>
                <p className="metrics-section-title">
                  <span className="dot long" />
                  Long-term view
                </p>
                <div className="metrics-table-wrap">
                  <table className="metrics-table">
                    <tbody>
                      <tr>
                        <td className="label"><LabelWithTooltip label="P/E ratio" tooltip={METRIC_TOOLTIPS.pe} /></td>
                        <td className="value">{longTermMetrics?.pe_ratio?.toFixed(1)}</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Market cap" tooltip={METRIC_TOOLTIPS.marketCap} /></td>
                        <td className="value">${(longTermMetrics?.market_cap / 1e12)?.toFixed(2)}T</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="52w range" tooltip={METRIC_TOOLTIPS.range52w} /></td>
                        <td className="value">
                          ${longTermMetrics?.fifty_two_week_low?.toFixed(0)} – ${longTermMetrics?.fifty_two_week_high?.toFixed(0)}
                        </td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Div yield" tooltip={METRIC_TOOLTIPS.divYield} /></td>
                        <td className="value">{longTermMetrics?.dividend_yield?.toFixed(2)}%</td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="Analyst target" tooltip={METRIC_TOOLTIPS.analystTarget} /></td>
                        <td className={`value ${longTermMetrics?.analyst_target >= dayMetrics?.price ? 'up' : 'down'}`}>
                          ${longTermMetrics?.analyst_target?.toFixed(0)}
                        </td>
                      </tr>
                      <tr>
                        <td className="label"><LabelWithTooltip label="YTD return" tooltip={METRIC_TOOLTIPS.ytd} /></td>
                        <td className={`value bold ${longTermMetrics?.ytd_return >= 0 ? 'up' : 'down'}`}>
                          {longTermMetrics?.ytd_return >= 0 ? '+' : ''}{longTermMetrics?.ytd_return?.toFixed(1)}%
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* News */}
            {news.length > 0 && (
              <div style={{ marginTop: '22px' }}>
                <p className="metrics-section-title">Recent news</p>
                <div className="news-list">
                  {news.map((item, index) => {
                    const sentimentClass = getSentimentClass(item.sentiment || 0);
                    return (
                      <a
                        key={index}
                        href={item.url || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`news-item ${sentimentClass}`}
                        style={{ display: 'block', textDecoration: 'none', cursor: item.url ? 'pointer' : 'default' }}
                      >
                        <div className="news-meta">
                          <span className="news-source">{item.source || 'Reuters'} · {item.published_date}</span>
                          <span className={`news-score ${sentimentClass}`}>
                            {item.sentiment >= 0 ? '+' : ''}{item.sentiment?.toFixed(2)}
                          </span>
                        </div>
                        <p className="news-title">{item.headline || item.title}</p>
                      </a>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default StockDetail;
