""" Modular Trading Bot - Adapted for custom strategy """
import os
import time
import asyncio
import traceback
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# These imports are crucial for the bot to function correctly within the project
from exchanges import ExchangeFactory
from helpers.trading_logger import TradingLogger
from helpers.lark_bot import LarkBot
from helpers.telegram_bot import TelegramBot


@dataclass
class TradingConfig:
    """Configuration class for trading parameters."""
    ticker: str
    contract_id: str
    quantity: Decimal
    take_profit: Decimal
    tick_size: Decimal
    direction: str
    max_orders: int
    wait_time: int
    exchange: str
    grid_step: Decimal
    stop_price: Decimal
    pause_price: Decimal
    aster_boost: bool

    @property
    def close_order_side(self) -> str:
        """Get the close order side based on bot direction."""
        return 'buy' if self.direction == "sell" else 'sell'


class TradingBot:
    """
    Modular Trading Bot with a custom strategy to maintain a target position value.
    """

    def __init__(self, config: TradingConfig):
        """
        Initializes the TradingBot, creating its own logger and exchange client.
        This is the correct structure for this project.
        """
        self.config = config

        # 1. Create the logger
        self.logger = TradingLogger(
            f"{self.config.exchange.upper()}_{self.config.ticker.upper()}"
        )

        # 2. Create the exchange client using the factory
        try:
            factory = ExchangeFactory()
            self.exchange_client = factory.create_exchange(
                self.config.exchange, self.config, self.logger
            )
        except ValueError as e:
            self.logger.log(f"Fatal Error: Failed to create exchange client: {e}", "ERROR")
            raise

        self.shutdown_requested = False
        self.logger.log("TradingBot initialized successfully.")


    async def graceful_shutdown(self, reason: str = "Unknown"):
        """Perform graceful shutdown of the trading bot."""
        self.logger.log(f"Starting graceful shutdown: {reason}", "INFO")
        self.shutdown_requested = True
        try:
            # Disconnect from exchange
            await self.exchange_client.disconnect()
            self.logger.log("Graceful shutdown completed", "INFO")
        except Exception as e:
            self.logger.log(f"Error during graceful shutdown: {e}", "ERROR")


    async def run(self):
        """
        Main trading loop with your custom target USD shorting logic.
        """
        try:
            # --- Your Trading Strategy Parameters ---
            TARGET_SHORT_USD = 1000.0  # The desired value of your short position in USD
            MIN_ORDER_USD = 5.0      # The minimum order size in USD to execute a trade

            self.logger.log("=== Custom Trading Configuration ===", "INFO")
            self.logger.log(f"Ticker: {self.config.ticker}", "INFO")
            self.logger.log(f"Exchange: {self.config.exchange}", "INFO")
            self.logger.log(f"Target Short Value: ${TARGET_SHORT_USD:,.2f}", "INFO")
            self.logger.log(f"Wait Time: {self.config.wait_time}s", "INFO")
            self.logger.log("====================================", "INFO")

            # Connect to exchange
            await self.exchange_client.connect()
            await asyncio.sleep(5)  # Wait for connection to establish

            # --- Main Trading Loop ---
            while not self.shutdown_requested:
                try:
                    # Step 1: Get current market price
                    current_price = await self.exchange_client.get_token_price(self.config.ticker)
                    if current_price is None:
                        raise ValueError(f"Could not fetch price for {self.config.ticker}")
                    self.logger.log(f"Current {self.config.ticker} price: ${current_price:,.4f}")

                    # Step 2: Get your current position
                    current_position_qty = await self.exchange_client.get_short_position(self.config.ticker)
                    if current_position_qty is None:
                        raise ValueError(f"Could not fetch position for {self.config.ticker}")

                    current_position_usd = current_position_qty * current_price
                    self.logger.log(f"Current short position: {current_position_qty:.4f} {self.config.ticker} (${current_position_usd:,.2f})")

                    # Step 3: Calculate the difference and decide on an order
                    position_delta_usd = TARGET_SHORT_USD - current_position_usd

                    if abs(position_delta_usd) > MIN_ORDER_USD:
                        order_side = "sell" if position_delta_usd > 0 else "buy"
                        order_size_usd = abs(position_delta_usd)
                        order_size_qty = order_size_usd / current_price

                        self.logger.log(f"Target deviation detected. Placing {order_side.upper()} order for "
                                        f"{order_size_qty:.4f} {self.config.ticker} (${order_size_usd:,.2f})", "WARNING")

                        # Step 4: Place the market order
                        await self.exchange_client.place_market_order(
                            ticker=self.config.ticker,
                            side=order_side,
                            quantity=order_size_qty
                        )
                        self.logger.log("Market order placed successfully!", "INFO")

                    else:
                        self.logger.log("Position is within target range. No action needed.")

                except Exception as e:
                    self.logger.log(f"An error occurred in the trading loop: {e}", "ERROR")

                finally:
                    # Wait for the next cycle
                    self.logger.log(f"--- Sleeping for {self.config.wait_time} seconds ---")
                    await asyncio.sleep(self.config.wait_time)

        except KeyboardInterrupt:
            self.logger.log("Bot stopped by user")
            await self.graceful_shutdown("User interruption (Ctrl+C)")
        except Exception as e:
            self.logger.log(f"Critical error: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            await self.graceful_shutdown(f"Critical error: {e}")
        finally:
            self.logger.log("Bot shutdown complete.")
