import logging
import yfinance as yf

logger = logging.getLogger(__name__)

# ─── NSE (Nairobi Securities Exchange) Tickers ───────────────────────────────
# Yahoo Finance uses .NR suffix for Nairobi-listed stocks.
# This set covers all actively traded NSE tickers so the AI can just say
# [STOCK: SCOM] without needing to know about the .NR suffix.
NSE_TICKERS = {
    # Banking & Finance
    "SCOM", "KCB", "EQTY", "COOP", "ABSA", "SBIC", "NCBA", "DTB", "IMH", "BKG",
    "HF", "CIC", "BRIT", "JUB", "LKN", "KNRE",
    # Manufacturing & Industry
    "EABL", "BAT", "BOC", "CARB", "BAMB", "ARM", "CRG",
    # Energy & Petroleum
    "KEGN", "KPLC", "TOTAL", "UMME",
    # Telecom & Tech
    "SCOM", "AIRTEL",
    # Investment & Holding
    "CTUM", "BRIT", "ICDC", "OCH", "KURV",
    # Agriculture
    "SASN", "KUKZ", "LIMT", "WTK", "REA", "EGAD", "KAPC",
    # Real Estate & Construction
    "HOME", "KURV",
    # Insurance
    "CIC", "JUB", "LKN", "BRIT", "KNRE",
    # Retail & Services
    "UCHM", "SGL", "NMG", "TPS", "SCAN", "HAFR",
    # Other common
    "FIRE", "KENO", "MSC", "EVRD", "WILL",
}


def get_stock_price(symbol):
    """Gets live price for Stocks, Crypto, or Forex.
    
    Supports:
    - Kenyan stocks: SCOM, KCB, EQTY, etc. (auto-adds .NR suffix)
    - US stocks: AAPL, MSFT, TSLA, etc.
    - Crypto: BTC-USD, ETH-USD
    - Forex: USDKES=X, EURUSD=X
    """
    try:
        # Clean the symbol
        symbol = symbol.replace('[', '').replace(']', '').strip().upper()
        
        logger.info(f"Checking price for: {symbol}")

        # Auto-detect NSE stocks and add .NR suffix
        # Handles both "SCOM" and "SCOM.NR" (don't double-suffix)
        lookup = symbol
        if symbol in NSE_TICKERS:
            lookup = f"{symbol}.NR"
        elif symbol.replace(".NR", "") in NSE_TICKERS:
            lookup = symbol  # already has .NR

        ticker = yf.Ticker(lookup)
        
        # Try 1d first, fall back to 5d if market is closed
        data = ticker.history(period="1d")
        if data.empty:
            data = ticker.history(period="5d")

        if not data.empty:
            price = data['Close'].iloc[-1]
            open_price = data['Open'].iloc[-1]
            high = data['High'].iloc[-1]
            low = data['Low'].iloc[-1]

            # Get currency and name
            info = ticker.info or {}
            currency = info.get('currency', 'KES' if lookup.endswith('.NR') else 'USD')
            name = info.get('shortName', symbol)

            # Calculate daily change
            change = price - open_price
            change_pct = (change / open_price * 100) if open_price else 0
            arrow = "🟢" if change >= 0 else "🔴"

            return (
                f"📈 **{name}** ({symbol})\n"
                f"💰 Price: **{price:,.2f} {currency}**\n"
                f"{arrow} Change: {change:+,.2f} ({change_pct:+.2f}%)\n"
                f"📊 High: {high:,.2f} | Low: {low:,.2f}"
            )
        else:
            logger.warning(f"No data returned for {lookup}")
            return None

    except Exception as e:
        logger.error(f"Stock error for {symbol}: {e}")
        return None