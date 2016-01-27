#!/usr/bin/env python3
# coding: utf-8

import logging
import pathlib

import click
import tornado.ioloop
import tornado.template
import tornado.web


class Configuration:
    COINBASE_API_ENDPOINT = "https://api.coinbase.com/v2/"
    COINBASE_API_ENDPOINT_SANDBOX = "https://api.sandbox.coinbase.com/"
    COINBASE_API_KEY = "dOjIYwTJClFK7pt6"
    COINBASE_API_SECRET = "yHnBgl62iUkpVGEs6NTUCoabejWsyP1D"
    COOKIE_SECRET = b"One wallet to rule them all"
    HTTP_PORT = 8080
    LOG_FORMAT = " ".join((
        click.style("%(asctime)s", dim=True),
        click.style("%(module)s", fg="green"),
        click.style("[%(levelname)s]", fg="cyan"),
        click.style("%(message)s", bold=True),
    ))


class Application(tornado.web.Application):

    def __init__(self):
        template_path = pathlib.Path(__file__).absolute().parent
        favicon_path = pathlib.Path(__file__).absolute().parent / "favicomatic"

        logging.debug("Template path is set to: %s", template_path)
        logging.debug("Favicon path is set to: %s", favicon_path)

        super().__init__(
            [
                (r"/", HomeRequestHandler),
                (r"/((apple-touch-icon|favicon|mstile).*)", tornado.web.StaticFileHandler, {"path": str(favicon_path)}),
            ],
            cookie_secret=Configuration.COOKIE_SECRET,
            xsrf_cookies=True,
            template_path=str(template_path),
        )


class HomeRequestHandler(tornado.web.RequestHandler):

    LAST_SENT_TIMESTAMP_COOKIE = "lst"

    @tornado.web.removeslash
    def get(self):
        # TODO: test and set cookie.
        self.render("home.html")

    def post(self):
        # TODO: test cookie, test anti-robot, send money and set cookie.
        self.render("home.html")


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
    Application().listen(Configuration.HTTP_PORT)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
