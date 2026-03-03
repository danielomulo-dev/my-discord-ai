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
        # 1. Clean the symbol
        symbol = symbol.replace('[', '').replace(']', '').replace('STOCK:', '').strip().upper()
        
        # 2. Handle NSE Suffix (.NR)
        lookup = symbol
        is_nse = False
        if symbol in NSE_TICKERS:
            lookup = f"{symbol}.NR"
            is_nse = True
        elif symbol.endswith(".NR"):
            is_nse = True

        logger.info(f"Fetching data for: {lookup}")
        ticker = yf.Ticker(lookup)

        # 3. Fast Data Fetch (Only get the last 5 days of history)
        # Avoid using ticker.info because it is VERY slow and often fails
        data = ticker.history(period="5d")
        
        if data.empty:
            logger.warning(f"No price data found for {lookup}")
            return f"*(Manze, I couldn't find live prices for {symbol} right now.)*"

        # Get the latest close and the previous close for change calculation
        price = data['Close'].iloc[-1]
        
        # 4. Logic for NSE vs Global Currencies
        currency = "KES" if is_nse else "USD"
        
        # 5. Calculate Performance
        try:
            # We use the previous day's close for a more accurate 'Daily Change'
            prev_close = data['Close'].iloc[-2] if len(data) > 1 else data['Open'].iloc[-1]
            change = price - prev_close
            change_pct = (change / prev_close * 100)
            
            arrow = "🟢" if change >= 0 else "🔴"
            sign = "+" if change >= 0 else ""

            return (
                f"📈 **{symbol} (NSE)**\n" if is_nse else f"📈 **{symbol}**\n"
                f"**Price:** {price:,.2f} {currency}\n"
                f"{arrow} Change: {sign}{change:,.2f} ({sign}{change_pct:.2f}%)"
            )
        except Exception as e:
            # Fallback for simple price if math fails
            return f"📈 **{symbol} Price:** {price:,.2f} {currency}"

    except Exception as e:
        logger.error(f"Stock error for {symbol}: {e}")
        return None