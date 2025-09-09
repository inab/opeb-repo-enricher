#!/usr/bin/env python3

import abc
import configparser
import datetime
import json
import logging
import time
from typing import (
    cast,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Iterable,
        Mapping,
        MutableSequence,
        Optional,
        Sequence,
        Tuple,
        TypeAlias,
        Union,
    )

    from typing_extensions import (
        Buffer,
    )

    import urllib.request
    import urllib.response
    from _typeshed import (
        SupportsRead,
    )

    from mypy_extensions import (
        DefaultArg,
    )

    URLOpener: TypeAlias = Callable[
        [
            Union[str, urllib.request.Request],
            DefaultArg(Optional[Union[Buffer, SupportsRead[bytes], Iterable[bytes]]]),
            DefaultArg(Optional[float]),
        ],
        urllib.response.addinfourl,
    ]

import urllib
import urllib.parse

from ..common import get_opener_with_auth


class RepoMatcherException(Exception):
    pass


class AbstractRepoMatcher(abc.ABC):
    # Common constants

    recognizedBuildSystemsByLang = {"Makefile": "make", "CMake": "cmake"}

    recognizedInterpretedLanguages = set(
        (
            "python",
            "perl",
            "ruby",
            "r",
            "php",
            "golang",
            "javascript",
            "shell",
            "jsoniq",
        )
    )

    recognizedCompiledLanguages = set(
        (
            "c",
            "c++",
            "java",
            "fortran",
            "perl 6",
            "pascal",
            "objective-c",
            "component pascal",
            "scala",
        )
    )

    def __init__(self, config: "configparser.ConfigParser"):
        if not isinstance(config, configparser.ConfigParser):
            raise RepoMatcherException(
                "Expected a configparser.ConfigParser instance as parameter"
            )

        # Getting a logger focused on specific classes
        import inspect

        self.logger = logging.getLogger(
            dict(inspect.getmembers(self))["__module__"]
            + "::"
            + self.__class__.__name__
        )

        self.config = config
        self.req_period: "Optional[float]" = None
        self._opener = self._getOpener()
        self._remaining: "Optional[int]" = None
        self._resettime: "Optional[int]" = None

    def getNumReqAndReset(self) -> "Tuple[int, int]":
        """
        It returns what it is set up in the configuration file
        and it assumes 1 hour to reset the counter
        """
        if self._remaining is None:
            self._remaining = self.config.getint(
                self.kind(),
                "numreq",
                fallback=self.config.getint("default", "numreq", fallback=3600),
            )
            self._resettime = (
                round(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 3600
            )

        return (
            self.config.getint(
                self.kind(),
                "numreq",
                fallback=self.config.getint("default", "numreq", fallback=3600),
            ),
            round(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 3600,
        )

    def reqPeriod(self) -> "float":
        if self.req_period is None:
            config = self.config
            numreq = config.getint(
                self.kind(),
                "numreq",
                fallback=config.getint("default", "numreq", fallback=3600),
            )
            self.req_period = 3600 / numreq

        return self.req_period

    def updatePeriod(self, response: "urllib.response.addinfourl") -> "None":
        """
        This method is going to be overloaded by GitHub
        """
        pass

    @classmethod
    @abc.abstractmethod
    def kind(cls) -> "str":
        pass

    @abc.abstractmethod
    def doesMatch(self, uriStr: "str") -> "Tuple[bool, Optional[str], Optional[str]]":
        pass

    @abc.abstractmethod
    def getRepoData(self, fullrepo: "Mapping[str, Any]") -> "Mapping[str, Any]":
        pass

    @abc.abstractmethod
    def _getCredentials(self) -> "Tuple[str, Optional[str], Optional[str]]":
        return "https://www.example.org", None, None

    def _getOpener(self) -> "URLOpener":
        top_level_url, user, token = self._getCredentials()

        return (
            urllib.request.urlopen
            if (user is None or token is None)
            else get_opener_with_auth(top_level_url, user, token).open
        )

    def fetchJSON(
        self,
        bUri: "Union[str, urllib.parse.ParseResult]",
        p_acceptHeaders: "Optional[str]" = None,
        numIter: "int" = 0,
        period: "Optional[float]" = None,
    ) -> "Tuple[bool, Sequence[Mapping[str, Any]]]":
        """
        Shared method to fetch data from repos
        """

        if isinstance(bUri, urllib.parse.ParseResult):
            uriStr = urllib.parse.urlunparse(bUri)
        else:
            uriStr = bUri

        bData: "MutableSequence[Mapping[str, Any]]" = []
        if period is None:
            period = self.reqPeriod()

        is_success = True
        while is_success:
            bUriStr = uriStr
            uriStr = ""

            req = urllib.request.Request(bUriStr)
            if p_acceptHeaders is not None:
                req.add_header("Accept", p_acceptHeaders)

            # To honor the limit of 5000 requests per hour
            t0 = time.time()
            linkH = None
            try:
                with self._opener(req) as response:
                    newBData: "Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]" = json.load(
                        response
                    )
                    linkH = response.getheader("Link")

            except json.JSONDecodeError as jde:
                raise RepoMatcherException(
                    f"JSON parsing error on {bUriStr}: {jde.msg}"
                ) from jde
            except urllib.error.HTTPError as he:
                self.logger.exception(f"Kicked out {bUriStr}: {he.code}")
                is_success = False
                # raise RepoMatcherException(f'Kicked out {bUriStr}: {he.code}') from he
            except urllib.error.URLError as ue:
                raise RepoMatcherException(f"Kicked out {bUriStr}: {ue.reason}") from ue
            except Exception as e:
                raise RepoMatcherException(f"Kicked out {bUriStr}") from e

            except Exception:
                # Show must go on
                self.logger.exception(f"Kicked out {bUriStr}")
                is_success = False
            else:
                # Assuming it is an array
                if isinstance(newBData, list):
                    bData.extend(newBData)
                else:
                    bData.append(cast("Mapping[str, Any]", newBData))

                # Are we paginating?
                if isinstance(linkH, str) and len(linkH) > 0:
                    for link in linkH.split(", "):
                        splitSemi = link.split("; ")
                        newLink = splitSemi[0]
                        newRel = splitSemi[1] if len(splitSemi) > 0 else None

                        if newRel == "rel='next'":
                            newLink = newLink.translate(str.maketrans("", "", "<>"))
                            uriStr = newLink
                            numIter -= 1
                            break

            # Should we sleep?
            leap = time.time() - t0
            if period > leap:
                time.sleep(period - leap)

            # Simulating a do ... while
            if len(uriStr) == 0 or numIter == 0:
                break

        return is_success, bData
