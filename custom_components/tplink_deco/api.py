import asyncio
import base64
import hashlib
import json
import logging
import math
import re
import secrets
from typing import Any
from urllib.parse import quote_plus

import aiohttp
import async_timeout
from aiohttp.hdrs import CONTENT_TYPE
from aiohttp.hdrs import COOKIE
from aiohttp.hdrs import SET_COOKIE
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes

from .exceptions import AuthException

TIMEOUT = 10

AES_KEY_BYTES = 16
MIN_AES_KEY = 10 ** (AES_KEY_BYTES - 1)
MAX_AES_KEY = 10 ** AES_KEY_BYTES - 1

PKCS1_v1_5_HEADER_BYTES = 11

_LOGGER: logging.Logger = logging.getLogger(__package__)


def byte_len(n: int) -> int:
    return (int(math.log2(n)) + 8) >> 3


def rsa_encrypt(n: int, e: int, plaintext: bytes) -> bytes:
    """
    RSA encrypts plaintext. TP-Link breaks the plaintext down into blocks and concatenates the output.
    :param n: The RSA public key's n value
    :param e: The RSA public key's e value
    :param plaintext: The data to encrypt
    :return: RSA encrypted ciphertext
    """
    public_key = RSA.construct((n, e)).publickey()
    encryptor = PKCS1_v1_5.new(public_key)
    block_size = byte_len(n)
    bytes_per_block = block_size - PKCS1_v1_5_HEADER_BYTES

    encrypted_text = ""
    text_bytes = len(plaintext)
    index = 0
    while index < text_bytes:
        content_num_bytes = min(bytes_per_block, text_bytes - index)
        content = plaintext[index : index + content_num_bytes]
        encrypted_text += encryptor.encrypt(content).hex()
        index += content_num_bytes

    return encrypted_text


def aes_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """
    AES-CBC encrypt with PKCS #7 padding. This matches the AES options on TP-Link routers.
    :param key: The AES key
    :param iv: The AES IV
    :param plaintext: Data to encrypt
    :return: Ciphertext
    """
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    plaintext_bytes: bytes = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext_bytes) + encryptor.finalize()
    return ciphertext


def aes_decrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """
    AES-CBC decrypt with PKCS #7 padding.
    :param key: The AES key
    :param iv: The AES IV
    :param plaintext: Data to encrypt
    :return: Ciphertext
    """
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    ciphertext = decryptor.update(plaintext) + decryptor.finalize()
    return ciphertext


class TplinkDecoApi:
    def __init__(
        self, host: str, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._session = session

        self._aes_key = None
        self._aes_key_bytes = None
        self._aes_iv = None
        self._aes_iv_bytes = None

        self._password_rsa_n = None
        self._password_rsa_e = None
        self._sign_rsa_n = None
        self._sign_rsa_e = None

        self._seq = None
        self._stok = None
        self._cookie = None

    async def async_list_clients(self) -> dict:
        if self._aes_key is None:
            self.generate_aes_key_and_iv()

        if self._password_rsa_n is None:
            await self.async_fetch_keys()

        if self._seq is None or self._stok is None:
            await self.async_fetch_auth()
            await self.async_login()

        client_payload = {"operation": "read", "params": {"device_mac": "default"}}
        response_json = await self._async_post(
            "List Clients",
            f"http://{self._host}/cgi-bin/luci/;stok={self._stok}/admin/client",
            params={"form": "client_list"},
            data=self._encode_payload(client_payload),
        )

        data = self._decrypt_data("List Clients", response_json["data"])
        error_code = data.get("error_code")
        if error_code != 0:
            raise Exception(f"List clients error {error_code}")

        client_list = data["result"]["client_list"]
        # client_list is only the connected clients
        _LOGGER.debug(f"client_list={client_list}")

        clients = {}
        for client in client_list:
            clients[client["mac"]] = client
            client["name"] = base64.b64decode(client["name"]).decode()

        return clients

    def generate_aes_key_and_iv(self):
        # TPLink requires key and IV to be a 16 digit number (no leading 0s)
        self._aes_key = secrets.randbelow(MAX_AES_KEY - MIN_AES_KEY) + MIN_AES_KEY
        self._aes_iv = secrets.randbelow(MAX_AES_KEY - MIN_AES_KEY) + MIN_AES_KEY
        self._aes_key_bytes = str(self._aes_key).encode("utf-8")
        self._aes_iv_bytes = str(self._aes_iv).encode("utf-8")
        _LOGGER.debug(f"aes_key={self._aes_key}")
        _LOGGER.debug(f"aes_iv={self._aes_iv}")

    async def async_fetch_keys(self):
        response_json = await self._async_post(
            "Fetch keys",
            f"http://{self._host}/cgi-bin/luci/;stok=/login",
            params={"form": "keys"},
            data=json.dumps({"operation": "read"}),
        )

        keys = response_json["result"]["password"]
        self._password_rsa_n = int(keys[0], 16)
        self._password_rsa_e = int(keys[1], 16)
        _LOGGER.debug(f"password_rsa_n={self._password_rsa_n}")
        _LOGGER.debug(f"password_rsa_e={self._password_rsa_e}")

    async def async_fetch_auth(self):
        response_json = await self._async_post(
            "Fetch auth",
            f"http://{self._host}/cgi-bin/luci/;stok=/login",
            params={"form": "auth"},
            data=json.dumps({"operation": "read"}),
        )

        auth_result = response_json["result"]
        auth_key = auth_result["key"]
        self._sign_rsa_n = int(auth_key[0], 16)
        _LOGGER.debug(f"sign_rsa_n={self._sign_rsa_n}")
        self._sign_rsa_e = int(auth_key[1], 16)
        _LOGGER.debug(f"sign_rsa_e={self._sign_rsa_e}")

        self._seq = auth_result["seq"]
        _LOGGER.debug(f"seq={self._seq}")

    async def async_login(self):
        password_encrypted = rsa_encrypt(
            self._password_rsa_n, self._password_rsa_e, self._password.encode()
        )

        login_payload = {
            "params": {"password": password_encrypted},
            "operation": "login",
        }
        response_json = await self._async_post(
            "Login",
            f"http://{self._host}/cgi-bin/luci/;stok=/login",
            params={"form": "login"},
            data=self._encode_payload(login_payload),
        )

        data = self._decrypt_data("Login", response_json["data"])
        error_code = data["error_code"]
        result = data["result"]
        if error_code == -5002:
            attempts = result["attemptsAllowed"]
            raise AuthException(
                f"Invalid login credentials. {attempts} attempts remaining."
            )
        if error_code != 0:
            raise Exception(f"Login error {data['error_code']}")

        self._stok = result["stok"]
        _LOGGER.debug(f"stok={self._stok}")

        if self._cookie is None:
            raise Exception("Login response did not have a Set-Cookie header")

    async def _async_post(
        self, context: str, url: str, params: dict[str:Any], data: Any
    ) -> dict:
        headers = {CONTENT_TYPE: "application/json"}
        if self._cookie is not None:
            headers[COOKIE] = self._cookie
        try:
            async with async_timeout.timeout(TIMEOUT):
                response = await self._session.post(
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                )
                response.raise_for_status()

                cookie = response.headers.get(SET_COOKIE)
                if cookie is not None:
                    match = re.search(r"(sysauth=[a-f0-9]+)", cookie)
                    if match:
                        self._cookie = match.group(1)
                        _LOGGER.debug(f"cookie={self._cookie}")

                # Sometimes server responses with incorrect content type, so disable the check
                response_json = await response.json(content_type=None)
                _LOGGER.debug(
                    "%s: response_json %s",
                    context,
                    response_json,
                )
                if "error_code" in response_json:
                    error_code = response_json.get("error_code")
                    if error_code != 0:
                        raise Exception(f"{context} error: {error_code}")

                return response_json
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "%s timed out",
                context,
            )
            raise err
        except (aiohttp.ClientResponseError) as err:
            _LOGGER.error(
                "%s client response error: %s",
                context,
                err,
            )
            if err.status == 401 or err.status == 403:
                self._clear_auth()
                raise AuthException from err
            raise err
        except (aiohttp.ClientError) as err:
            _LOGGER.error(
                "%s client error: %s",
                context,
                err,
            )
            raise err
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error(
                "%s error: %s",
                context,
                err,
            )
            raise err

    def _encode_payload(self, payload: Any):
        data = self._encode_data(payload)
        sign = self._encode_sign(len(data))
        # Must URI encode data after calculating data length
        payload = f"sign={sign}&data={quote_plus(data)}"
        return payload

    def _encode_sign(self, data_len: int):
        seq_with_data_len = self._seq + data_len
        auth_hash = (
            hashlib.md5(f"{self._username}{self._password}".encode()).digest().hex()
        )
        sign_text = (
            f"k={self._aes_key}&i={self._aes_iv}&h={auth_hash}&s={seq_with_data_len}"
        )
        sign = rsa_encrypt(self._sign_rsa_n, self._sign_rsa_e, sign_text.encode())
        return sign

    def _encode_data(self, payload: Any):
        payload_json = json.dumps(payload, separators=(",", ":"))

        data_encrypted = aes_encrypt(
            self._aes_key_bytes, self._aes_iv_bytes, payload_json.encode()
        )
        data = base64.b64encode(data_encrypted).decode()
        return data

    def _clear_auth(self):
        self._seq = None
        self._stok = None
        self._cookie = None

    def _decrypt_data(self, context: str, data: str):
        if data == "":
            self._clear_auth()
            raise Exception("Need to re-login")

        data_decoded = base64.b64decode(data)
        data_decrypted = aes_decrypt(
            self._aes_key_bytes, self._aes_iv_bytes, data_decoded
        )
        # Remove the PKCS #7 padding
        num_padding_bytes = int(data_decrypted[-1])
        data_decrypted = data_decrypted[:-num_padding_bytes].decode()
        data_json = json.loads(data_decrypted)
        _LOGGER.debug(
            "%s data_json: %s",
            context,
            data_json,
        )
        return data_json
