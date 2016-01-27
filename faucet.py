#!/usr/bin/env python3
# coding: utf-8

import http
import logging
import pathlib
import pickle
import time

import click
import redis
import tornado.ioloop
import tornado.template
import tornado.web


class Configuration:
    # Coinbase API endpoints.
    COINBASE_API_ENDPOINT = "https://api.coinbase.com/v2/"
    COINBASE_API_ENDPOINT_SANDBOX = "https://api.sandbox.coinbase.com/"
    # Coinbase API key.
    COINBASE_API_KEY = "dOjIYwTJClFK7pt6"
    COINBASE_API_SECRET = "yHnBgl62iUkpVGEs6NTUCoabejWsyP1D"
    # Cookies.
    COOKIE_LAST_EARN_TIMESTAMP = "let"
    COOKIE_SECRET = b"One wallet to rule them all"
    # Web server.
    HTTP_PORT = 8080
    # Logging.
    LOG_FORMAT = " ".join((
        click.style("%(asctime)s", dim=True),
        click.style("%(module)s", fg="green"),
        click.style("[%(levelname)s]", fg="cyan"),
        click.style("%(message)s", bold=True),
    ))
    # Game balance.
    EARN_WAITING_TIME_MINUTES = 1
    EARN_WAITING_TIME = 60.0 * EARN_WAITING_TIME_MINUTES
    # Redis.
    REDIS_EARN_TIME_EXPIRE = 24 * 60 * 60
    REDIS_EARN_TIME_KEY_FORMAT = "faucet:%s:earn_time"


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


class HomeRequestHandler(tornado.web.RequestHandler):

    # noinspection PyMethodOverriding
    def initialize(self, database: redis.StrictRedis):
        # noinspection PyAttributeOutsideInit
        self.database = database

    @tornado.web.removeslash
    def get(self):
        self.handle(self.get_cookie_waiting_time())

    def post(self):
        if self.get_body_argument("c") != "js":
            # This is either a robot or a human with disabled JavaScript.
            raise tornado.web.HTTPError(http.HTTPStatus.BAD_REQUEST.value, "Are you a bot?")

        wallet_address = self.get_body_argument("wallet_address")
        wallet_key = Configuration.REDIS_EARN_TIME_KEY_FORMAT % wallet_address

        # Check waiting time.
        waiting_time = self.get_cookie_waiting_time()
        if waiting_time > 0.0:
            self.handle(waiting_time)
            return
        wallet_cookie = self.database.get(wallet_key)
        if wallet_cookie:
            waiting_time = self.get_waiting_time(pickle.loads(wallet_cookie))
            if waiting_time > 0.0:
                self.handle(waiting_time)
                return

        # TODO: send money.
        logging.info("Send money to %s.", wallet_address)

        # Remember last earn time for the wallet and cookie.
        cookie = pickle.dumps(time.time())
        self.database.set(wallet_key, cookie, ex=Configuration.REDIS_EARN_TIME_EXPIRE)
        self.set_secure_cookie(Configuration.COOKIE_LAST_EARN_TIMESTAMP, cookie)

        # Render the page. We now that we've just sent money.
        self.handle(Configuration.EARN_WAITING_TIME)

    def handle(self, waiting_time: float):
        """
        We return the same response for both GET and POST.
        This method contains the shared logic.
        """
        self.render(
            "home.html",
            Configuration=Configuration,
            waiting_time=waiting_time,
        )

    def get_cookie_waiting_time(self) -> float:
        """
        Reads the cookie and gets remaining wait time.
        """
        cookie = self.get_secure_cookie(Configuration.COOKIE_LAST_EARN_TIMESTAMP)
        return self.get_waiting_time(pickle.loads(cookie) if cookie else 0)

    @staticmethod
    def get_waiting_time(earn_time: float) -> float:
        return earn_time + Configuration.EARN_WAITING_TIME - time.time()


@click.command()
@click.option("-l", "--log-file", help="Log file.", type=click.File("wt", encoding="utf-8"))
@click.option("-v", "--verbose", is_flag=True, help="Increase verbosity.")
def main(log_file, verbose: bool):
    """
    Bitcoin Faucet Application.
    """

    logging.basicConfig(
        format=Configuration.LOG_FORMAT,
        level=(logging.DEBUG if verbose else logging.INFO),
        stream=(log_file or click.get_text_stream("stderr")),
    )

    logging.info("Starting application on port %s…", Configuration.HTTP_PORT)
    Application(redis.StrictRedis()).listen(Configuration.HTTP_PORT)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
