import logging
import yfinance as yf

logger = logging.getLogger(__name__)

# NSE tickers - Yahoo Finance uses .NR suffix for Nairobi
NSE_TICKERS = {
    "SCOM", "KCB", "EQTY", "COOP", "ABSA", "SBIC", "NCBA", "DTB", "IMH", "BKG",
    "HF", "CIC", "BRIT", "JUB", "LKN", "KNRE",
    "EABL", "BAT", "BOC", "CARB", "BAMB", "ARM", "CRG",
    "KEGN", "KPLC", "TOTAL", "UMME",
    "AIRTEL",
    "CTUM", "ICDC", "OCH", "KURV",
    "SASN", "KUKZ", "LIMT", "WTK", "REA", "EGAD", "KAPC",
    "HOME",
    "UCHM", "SGL", "NMG", "TPS", "SCAN", "HAFR",
    "FIRE", "KENO", "MSC", "EVRD", "WILL",
}


def get_stock_price(symbol):
    """Gets live price for Stocks, Crypto, or Forex."""
    try:
        symbol = symbol.replace('[', '').replace(']', '').strip().upper()
        logger.info(f"Checking price for: {symbol}")

        # Auto-detect NSE stocks and add .NR suffix
        lookup = symbol
        if symbol in NSE_TICKERS:
            lookup = f"{symbol}.NR"
        elif symbol.endswith(".NR") and symbol.replace(".NR", "") in NSE_TICKERS:
            lookup = symbol

        ticker = yf.Ticker(lookup)

        # Get price data - try 1d first, fall back to 5d if market closed
        data = ticker.history(period="1d")
        if data.empty:
            data = ticker.history(period="5d")

        if data.empty:
            logger.warning(f"No data for {lookup}")
            return None

        price = data['Close'].iloc[-1]
        
        # Try to get extra info, but don't crash if it fails
        currency = "KES" if lookup.endswith(".NR") else "USD"
        try:
            info = ticker.info
            if info:
                currency = info.get('currency', currency)
        except Exception:
            pass  # info call failed, use default currency

        # Build response - try enriched, fall back to simple
        try:
            open_price = data['Open'].iloc[-1]
            high = data['High'].iloc[-1]
            low = data['Low'].iloc[-1]
            change = price - open_price
            change_pct = (change / open_price * 100) if open_price else 0
            arrow = "🟢" if change >= 0 else "🔴"

            return (
                f"📈 **{symbol} Price:** {price:,.2f} {currency}\n"
                f"{arrow} Change: {change:+,.2f} ({change_pct:+.2f}%)\n"
                f"📊 High: {high:,.2f} | Low: {low:,.2f}"
            )
        except Exception:
            # Fallback: just price (mirrors old working behavior)
            return f"📈 **{symbol} Price:** {price:,.2f} {currency}"

    except Exception as e:
        logger.error(f"Stock error for {symbol}: {e}")
        return None
