import math
from typing import Sequence, Mapping, Dict

from qf_lib.backtesting.broker.broker import Broker
from qf_lib.backtesting.contract.contract import Contract
from qf_lib.backtesting.contract_to_ticker_conversion.base import ContractTickerMapper
from qf_lib.backtesting.data_handler.data_handler import DataHandler
from qf_lib.backtesting.order.execution_style import ExecutionStyle
from qf_lib.backtesting.order.order import Order


class OrderFactory(object):
    def __init__(self, broker: Broker, data_handler: DataHandler, contract_to_ticker_mapper: ContractTickerMapper):
        self.broker = broker
        self.data_handler = data_handler
        self.contract_to_ticker_mapper = contract_to_ticker_mapper

    def orders(self, quantities: Mapping[Contract, int], execution_style: ExecutionStyle, time_in_force: str="DAY")\
            -> Sequence[Order]:
        """
        Creates a list of Orders for given numbers of shares for each given asset.

        Orders requiring 0 shares will be removed from resulting order list

        Parameters
        ----------
        quantities
            mapping of a Contract to an amount of shares which should be bought/sold.
            If number is positive then asset will be bought. Otherwise it will be sold.
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        """
        order_list = []
        for contract, quantity in quantities.items():
            if quantity != 0:
                order_list.append(Order(contract, quantity, execution_style, time_in_force))

        return order_list

    def target_orders(self, target_quantities: Mapping[Contract, int], execution_style: ExecutionStyle,
                      time_in_force: str="DAY", tolerance_quantities: Mapping[Contract, int]=None) -> Sequence[Order]:
        """
        Creates a list of Orders from a dictionary of desired target number of shares (number of shares which should be
        present in the portfolio after executing the Order).

        If the position doesn't already exist, the new Order is placed for the :target_quantity of shares.
        If the position does exist the Order for the difference between the target number of shares
        and the current number of shares is placed.

        Parameters
        ----------
        target_quantities
            mapping of a Contract to a target number of shares which should be present in the portfolio after the Order
            is executed
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        tolerance_quantities
            tell the us what it a tolerance to the target_quantities (in both directions) for each contract.
            The tolerance is expressed in shares.
            For example: assume that currently the portfolio contains 100 shares of asset A.
            then calling target_orders({A: 101}, ..., tolerance_quantities={A: 2}) will not generate any trades as
            the tolerance of 2 allows the allocation to be 100. while target value is 101.

            Another example:
            assume that currently the portfolio contains 100 shares of asset A.
            then calling target_value_order({A: 102}, ..., tolerance_quantities={A: 2}) will generate a BUY order
            for 2 shares

            if abs(target - actual) > tolerance
                buy or sell assets to match the target

            If tolerance for a specific contract is not provided it is assumed to be 0
        """
        # Dict of Contract -> Quantities of shares to buy/sell
        quantities = dict()

        if tolerance_quantities is None:
            tolerance_quantities = {}

        contract_to_positions = {position.contract(): position for position in self.broker.get_positions()}

        for contract, target_quantity in target_quantities.items():
            position = contract_to_positions.get(contract, None)
            tolerance_quantity = tolerance_quantities.get(contract, 0)

            current_quantity = 0
            if position is not None:
                current_quantity = position.quantity()

            quantity = target_quantity - current_quantity

            if abs(quantity) > tolerance_quantity and quantity != 0:  # tolerance_quantity can be 0
                quantities[contract] = quantity

        return self.orders(quantities, execution_style, time_in_force)

    def value_orders(self, values: Mapping[Contract, float], execution_style: ExecutionStyle, time_in_force: str="DAY")\
            -> Sequence[Order]:
        """
        Creates a list of Orders by specifying the amount of money which should be spent on each asset rather
        than the number of shares to buy/sell.

        Parameters
        ----------
        values
            mapping of a Contract to the amount of money which should be spent on the asset (expressed in the currency
            in which the asset is traded)
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        """
        quantities, _ = self._calculate_target_shares_and_tolerances(values)
        return self.orders(quantities, execution_style, time_in_force)

    def percent_orders(self, percentages: Mapping[Contract, float], execution_style: ExecutionStyle,
                       time_in_force: str="DAY") -> Sequence[Order]:
        """
        Creates a list of Orders by specifying the percentage of the current portfolio value which should be spent
        on each asset.

        Parameters
        ----------
        percentages
            mapping of a Contract to a percentage value of the current portfolio which should be allocated in the asset.
            This is specified as a decimal value (e.g. 0.5 means 50%)
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        """
        portfolio_value = self.broker.get_portfolio_value()
        values = {contract: portfolio_value * fraction for contract, fraction in percentages.items()}

        return self.value_orders(values, execution_style, time_in_force)

    def target_value_orders(self, target_values: Mapping[Contract, float], execution_style: ExecutionStyle,
                            time_in_force: str="DAY", tolerance_value=0.0) -> Sequence[Order]:
        """
        Creates a list of Orders by specifying how much should be allocated in each asset after the Orders
        have been executed.

        Example:
            if we've already have 10M invested in 'SPY US Equity' and you call this method with target value of 11M
            then only 1M will be spent on this asset

        Parameters
        ----------
        target_values
            mapping of a Contract to a value which should be allocated in the asset after the Order has been executed
            (expressed in the currency in which the asset is traded)
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        tolerance_value
            tell the us what it a tolerance to the target_values (in both directions).
            The tolerance is expressed in currency units.
            For example: assume that currently the portfolio contains asset A with allocation 10 000$.
            then calling target_value_order({A: 10 500}, ..., tolerance=1 000) will not generate any trades as
            the tolerance of 1 000 allows the allocation to be 10 000$. while target value is 10 500.

            Another example:
            For example: assume that currently the portfolio contains asset A with allocation 10 000$.
            then calling target_value_order({A: 13 000}, ..., tolerance=1 000) will generate a BUY order
            corresponding to 3000$ of shares The tolerance of 1 000 does not allow a difference of 3000$

            if abs(target - actual) > tolerance
                buy or sell assets to match the target

            Note: the currency unit value will be converted to nr of shares. It might cause an anomaly where for example
            difference is 1005$ and tolerance is 1000 and shares will not be traded because after
            converting the numbers to shares they give equal number
        """
        target_quantities, tolerance_quantities = \
            self._calculate_target_shares_and_tolerances(target_values, tolerance_value)

        return self.target_orders(target_quantities, execution_style, time_in_force, tolerance_quantities)

    def target_percent_orders(self, target_percentages: Mapping[Contract, float], execution_style: ExecutionStyle,
                              time_in_force: str="DAY", tolerance_percent=0.0) -> Sequence[Order]:
        """
        Creates an Order adjusting a position to a value equal to the given percentage of the portfolio.

        Parameters
        ----------
        target_percentages
            mapping of a Contract to a percentage of a current portfolio value which should be allocated in each asset
            after the Order has been carried out
        execution_style
            execution style of an order (e.g. MarketOrder, StopOrder, etc.)
        time_in_force
            e.g. 'DAY' (Order valid for one trading session), 'GTC' (good till cancelled)
        tolerance_percent
            tell the us what it a tolerance to the target_percentages (in both directions).
            The tolerance is expressed in percentage points (0.02 corresponds to 2pp of diff)
            For example: assume that currently the portfolio contains asset A with allocation weight of 0.24.
            then calling order_target_percent({A: 0.25}, ..., tolerance=0.02) will not generate any trades as
            the tolerance of 0.02 allows the allocation to be 0.24 while target percentage is 0.25.

            Another example:
            assume that currently the portfolio contains asset A with allocation weight of 0.24.
            then calling order_target_percent({A: 0.30}, ..., tolerance=0.01) will generate a BUY order corresponding to
            0.30 - 0.24 = 0.06 of the portfolio value. The tolerance of 0.01 does not allow a difference of 0.06

            if abs(target - actual) > tolerance
                buy or sell assets to match the target

            Note: percentages will be converted to nr of shares. It might cause an anomaly where for example
            difference is 0.123pp and tolerance is 0.120pp and shares will not be traded because after
            converting the numbers to shares they give equal number
        """
        portfolio_value = self.broker.get_portfolio_value()
        target_values = {
            contract: portfolio_value * target_percent for contract, target_percent in target_percentages.items()
        }
        tolerance_value = tolerance_percent * portfolio_value

        return self.target_value_orders(target_values, execution_style, time_in_force, tolerance_value)

    def _calculate_target_shares_and_tolerances(
            self, contract_to_amount_of_money: Mapping[Contract, float], tolerance_value=0.0)\
            -> (Mapping[Contract, int], Mapping[Contract, int]):
        """
        Returns
        ----------
        target_quantities
            Tells how many shares of each asset we should have in order to match the target

        tolerance_quantities
            Tells what is the tolerance (in number of shares) for each asset
        """
        tickers_to_contract_and_amount_of_money = self._make_tickers_to_contract_and_amount_of_money(
            contract_to_amount_of_money)

        tickers = list(tickers_to_contract_and_amount_of_money.keys())
        current_prices = self.data_handler.get_last_available_price(tickers)

        # Contract -> target number of shares
        target_quantities = dict()     # type: Dict[Contract, int]

        # Contract -> tolerance expressed as number of shares
        tolerance_quantities = dict()  # type: Dict[Contract, int]

        for ticker, (contract, amount_of_money) in tickers_to_contract_and_amount_of_money.items():
            current_price = current_prices.loc[ticker]

            target_quantity = math.floor(amount_of_money / current_price)  # type: int
            target_quantities[contract] = target_quantity

            tolerance_quantity = math.floor(tolerance_value / current_price)  # type: int
            tolerance_quantities[contract] = tolerance_quantity

        return target_quantities, tolerance_quantities

    def _make_tickers_to_contract_and_amount_of_money(self, contract_to_amount_of_money):
        tickers_to_contract_and_amount_of_money = dict()

        for contract, amount_of_money in contract_to_amount_of_money.items():
            ticker = self.contract_to_ticker_mapper.contract_to_ticker(contract)
            tickers_to_contract_and_amount_of_money[ticker] = contract, amount_of_money

        return tickers_to_contract_and_amount_of_money
