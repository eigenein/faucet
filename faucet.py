#!/usr/bin/env python3
# coding: utf-8

import decimal
import hashlib
import hmac
import json
import logging
import pathlib
import pickle
import time

import click
import redis
import tornado.gen
import tornado.httpclient
import tornado.ioloop
import tornado.template
import tornado.web


class Configuration:
    # Coinbase API production.
    COINBASE_API_KEY = "dOjIYwTJClFK7pt6"
    COINBASE_API_SECRET = b"yHnBgl62iUkpVGEs6NTUCoabejWsyP1D"
    COINBASE_API_TRANSACTIONS_PATH = "/v2/accounts/6f38ec6a-4f69-5e5e-aa27-7cac4a7227cd/transactions"
    COINBASE_API_TRANSACTIONS_URL = "https://api.coinbase.com" + COINBASE_API_TRANSACTIONS_PATH
    # Coinbase other.
    COINBASE_API_VERSION = "2016-01-27"
    COINBASE_API_MINIMUM_AMOUNT_BITS = 100
    # Cookies.
    COOKIE_LAST_EARN_TIMESTAMP = "let"
    COOKIE_SECRET = b"One wallet to rule them all"
    # Web server.
    HTTP_PORT = 8080
    # Logging.
    LOG_FORMAT_TTY = " ".join((
        click.style("%(asctime)s", dim=True),
        click.style("%(module)s", fg="green"),
        click.style("[%(levelname)s]", fg="cyan"),
        click.style("%(message)s", bold=True),
    ))
    LOG_FORMAT = "%(asctime)s %(module)s [%(levelname)s] %(message)s"
    # Game balance.
    EARN_WAITING_TIME_MINUTES = 1
    EARN_WAITING_TIME = 60.0 * EARN_WAITING_TIME_MINUTES
    EARN_AMOUNT_BITS = 1
    # Redis.
    REDIS_EARN_TIME_EXPIRE = 24 * 60 * 60
    REDIS_EARN_TIME_KEY_FORMAT = "faucet:%s:earn_time"
    REDIS_BALANCE_KEY_FORMAT = "faucet:%s:balance"
    REDIS_BALANCE_EXPIRE = 30 * 24 * 60 * 60
    # Coinbase API sandbox.
    # COINBASE_API_KEY = "PmfEFl20TP27qoLB"
    # COINBASE_API_SECRET = b"68UgM07f3XIK49Eglj0BAVfxFSoyR4qH"
    # COINBASE_API_TRANSACTIONS_PATH = "/v2/accounts/ac5b48f8-648e-5668-bf9f-6b8e980fe2e1/transactions"
    # COINBASE_API_TRANSACTIONS_URL = "https://api.sandbox.coinbase.com" + COINBASE_API_TRANSACTIONS_PATH


class Application(tornado.web.Application):

    def __init__(self, database: redis.StrictRedis):
        favicon_path = pathlib.Path(__file__).absolute().parent / "favicomatic"

        super().__init__(
            [
                (r"/", HomeRequestHandler, {"database": database}),
                (r"/((apple-touch-icon|favicon|mstile).*)", tornado.web.StaticFileHandler, {"path": str(favicon_path)}),
            ],
            cookie_secret=Configuration.COOKIE_SECRET,
            xsrf_cookies=True,
            template_path=str(pathlib.Path(__file__).absolute().parent),
            static_path=str(pathlib.Path(__file__).absolute().parent / "static"),
        )


# noinspection PyAbstractClass
class HomeRequestHandler(tornado.web.RequestHandler):

    bits_in_btc = decimal.Decimal(1000000)

    # noinspection PyMethodOverriding
    def initialize(self, database: redis.StrictRedis):
        # noinspection PyAttributeOutsideInit
        self.database = database

    def render(self, waiting_time: float, wallet_address="", balance=None, sent_amount=None):
        super().render(
            "home.html",
            Configuration=Configuration,
            waiting_time=waiting_time,
            wallet_address=wallet_address,
            balance=balance,
            sent_amount=sent_amount,
        )

    @tornado.web.removeslash
    def get(self):
        self.render(self.get_cookie_waiting_time())

    @tornado.gen.coroutine
    def post(self):
        if self.get_body_argument("c") != "js":
            # This is either a robot or a human with disabled JavaScript.
            raise tornado.web.HTTPError(400, "Are you a bot?")

        # Let's initialize the wallet info.
        wallet_address = self.get_body_argument("wallet_address")
        wallet_earn_time_key = Configuration.REDIS_EARN_TIME_KEY_FORMAT % wallet_address
        wallet_balance_key = Configuration.REDIS_BALANCE_KEY_FORMAT % wallet_address
        balance = self.safe_loads(self.database.get(wallet_balance_key), 0)

        # Check waiting time.
        waiting_time = self.get_cookie_waiting_time()
        if waiting_time > 0.0:
            self.render(waiting_time, wallet_address=wallet_address, balance=balance)
            return
        waiting_time = self.get_waiting_time(self.safe_loads(self.database.get(wallet_earn_time_key), 0.0))
        if waiting_time > 0.0:
            self.render(waiting_time, wallet_address=wallet_address, balance=balance)
            return

        # All checks passed. Increment balance.
        logging.info("Incrementing balance for %s (was %s Bits).", wallet_address, balance)
        balance += Configuration.EARN_AMOUNT_BITS
        sent_amount = 0
        # Save the balance to be on safe side.
        self.database.set(wallet_balance_key, pickle.dumps(balance), ex=Configuration.REDIS_BALANCE_EXPIRE)
        if balance >= Configuration.COINBASE_API_MINIMUM_AMOUNT_BITS:
            # Balance is large enough. Send money.
            logging.info("Sending %s Bits to %s…", balance, wallet_address)
            if (yield self.send_money(wallet_address, balance)):
                # Success.
                self.database.delete(wallet_balance_key)
                sent_amount, balance = balance, 0

        # Remember last earn time for the wallet and cookie.
        cookie = pickle.dumps(time.time())
        self.database.set(wallet_earn_time_key, cookie, ex=Configuration.REDIS_EARN_TIME_EXPIRE)
        self.set_secure_cookie(Configuration.COOKIE_LAST_EARN_TIMESTAMP, cookie)

        # Render the page. We know that we've just sent money.
        self.render(
            Configuration.EARN_WAITING_TIME,
            wallet_address=wallet_address,
            balance=balance,
            sent_amount=sent_amount,
        )

    def get_cookie_waiting_time(self) -> float:
        """
        Reads the cookie and gets remaining wait time.
        """
        return self.get_waiting_time(self.safe_loads(
            self.get_secure_cookie(Configuration.COOKIE_LAST_EARN_TIMESTAMP), 0))

    @staticmethod
    def get_waiting_time(earn_time: float) -> float:
        return earn_time + Configuration.EARN_WAITING_TIME - time.time()

    @staticmethod
    def safe_loads(bytes_object, default):
        return pickle.loads(bytes_object) if bytes_object is not None else default

    @tornado.gen.coroutine
    def send_money(self, wallet_address: str, amount_bits: int):
        request_body = json.dumps({
            "type": "send",
            "to": wallet_address,
            "amount": str(decimal.Decimal(amount_bits) / self.bits_in_btc),
            "currency": "BTC",
            "description": "Your free Bitcoins from https://bitcoin.eigenein.xyz – enjoy!",
            "skip_notifications": True,
        })
        timestamp = str(int(time.time()))

        http_response = yield tornado.httpclient.AsyncHTTPClient().fetch(
            tornado.httpclient.HTTPRequest(
                Configuration.COINBASE_API_TRANSACTIONS_URL,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "CB-VERSION": Configuration.COINBASE_API_VERSION,
                    "CB-ACCESS-KEY": Configuration.COINBASE_API_KEY,
                    "CB-ACCESS-TIMESTAMP": timestamp,
                    "CB-ACCESS-SIGN": hmac.new(
                        Configuration.COINBASE_API_SECRET,
                        msg=("%sPOST%s%s" % (
                            timestamp,
                            Configuration.COINBASE_API_TRANSACTIONS_PATH,
                            request_body,
                        )).encode("utf-8"),
                        digestmod=hashlib.sha256,
                    ).hexdigest(),
                },
                body=request_body,
            ),
            raise_error=False,
        )
        response_body = http_response.body.decode("utf-8")

        if http_response.code in (200, 201):
            response = json.loads(response_body)
            logging.info("Successfully sent money to %s. Transaction %s.", wallet_address, response["data"]["id"])
            return True

        logging.error(
            "Error while sending money to %s: %s %s",
            wallet_address, http_response.code, http_response.reason
        )
        logging.error("Headers: %s", list(http_response.request.headers.get_all()))
        logging.error("Request: %s", request_body)
        logging.error("Response: %s", response_body)
        return False


@click.command()
@click.option("-l", "--log-file", help="Log file.", type=click.File("at", encoding="utf-8"))
@click.option("-v", "--verbose", is_flag=True, help="Increase verbosity.")
def main(log_file, verbose: bool):
    """
    Bitcoin Faucet Application.
    """

    log_file = log_file or click.get_text_stream("stderr")
    logging.basicConfig(
        format=(Configuration.LOG_FORMAT_TTY if log_file.isatty() else Configuration.LOG_FORMAT),
        level=(logging.DEBUG if verbose else logging.INFO),
        stream=log_file,
    )

    logging.info("Starting application on port %s…", Configuration.HTTP_PORT)
    Application(redis.StrictRedis()).listen(Configuration.HTTP_PORT)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
