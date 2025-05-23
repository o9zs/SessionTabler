import asyncio
import html
import os
import re
import sqlite3
import time
from datetime import datetime

from rich.console import Console

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.types import PeerChannel

import config

client = TelegramClient("telethon", config.API_ID, config.API_HASH, system_version="5.9")

console = Console(highlight=False)
console.log()
connection = sqlite3.connect(os.path.join(config.sessions, "cache.db"))
cursor = connection.cursor()
 
cursor.execute("CREATE TABLE IF NOT EXISTS cache (session TEXT PRIMARY KEY, name TEXT, username TEXT, spamblock TEXT, task TEXT)")
connection.commit()
connection.close()

while True:
	table = {}

	for session in os.listdir(config.sessions):
		session, ext = os.path.splitext(session)

		if session in config.blacklist: continue

		if ext == ".session":
			def use_cached():
				console.log(f"Found [bold]{session}[/bold].session-journal")

				connection = sqlite3.connect(os.path.join(config.sessions, "cache.db"))
				cursor = connection.cursor()
				
				cached = cursor.execute("SELECT name, username, spamblock, task FROM cache WHERE session = ?", (session,)).fetchone()
				
				if cached == None:
					console.log(f"No data cached")

					table[session] = {}
				else:
					table[session] = {
						"name": cached[0],
						"username": cached[1],
						"spamblock": cached[2],
						"task": cached[3],
					}

					for key, value in table[session].items():
						console.log(f"{key.capitalize()}: [bold]{value}[/bold]")
					
				connection.close()
				console.print()

			if os.path.exists(os.path.join(config.sessions, f"{session}.session-journal")):
				use_cached()

				continue

			client = TelegramClient(os.path.join(config.sessions, session), config.API_ID, config.API_HASH, system_version="5.9")

			async def main():
				console.log(f"Connecting to [bold]{session}[/bold]...")

				try:
					await client.connect()
				except sqlite3.OperationalError:
					return use_cached()

				if not await client.is_user_authorized():
					console.log(f"[bold]{session}[/bold] is unauthorized")

					return await client.disconnect()
				
				console.log(f"Connected to [bold]{session}[/bold]")

				table[session] = {}
				
				me = await client.get_me()

				name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name

				table[session]["name"] = name
				table[session]["username"] = me.username

				console.log(f"Name: [bold]{name}[/bold]")
				console.log(f"Username: [bold]{me.username}[/bold]")

				async with client.conversation("@SpamBot") as conversation:
					await conversation.send_message("/start")

					try:
						response = await conversation.get_response()
					except asyncio.TimeoutError:
						console.log(f"[yellow]❌ TimeoutError while getting spamblock, using cached value[/yellow]")
				
						connection = sqlite3.connect(os.path.join(config.sessions, "cache.db"))
						cursor = connection.cursor()

						table[session]["spamblock"] = cursor.execute("SELECT spamblock FROM cache WHERE session = ?", (session,)).fetchone()[0]

						connection.close()
					else:
						await conversation.mark_read()

						if "Ограничения будут автоматически сняты" in response.text:
							table[session]["spamblock"] = "до " + re.search(
								r"Ограничения будут автоматически сняты (.*?) \(по московскому времени — на три часа позже\)",
								response.text
							).group(1)
						elif "Your account will be automatically released" in response.text:
							table[session]["spamblock"] = "до " + re.search(
								r"Your account will be automatically released on (.*?)\. Please note that if you repeat what got you limited and users report you again",
								response.text
							).group(1)
						elif "К сожалению, иногда наша антиспам-система излишне сурово реагирует на некоторые действия" in response.text or "Unfortunately, some actions can trigger a harsh response from our anti-spam systems" in response.text:
							table[session]["spamblock"] = "вечный"
						elif "Ваш аккаунт свободен" in response.text or "You’re free as a bird" in response.text:
							table[session]["spamblock"] = "отсутствует"

				console.log(f"Spamblock: [bold]{table[session]['spamblock']}[/bold]")

				table[session]["task"] = None

				console.log(f"Task: [bold]none[/bold]")
				
				connection = sqlite3.connect(os.path.join(config.sessions, "cache.db"))
				cursor = connection.cursor()

				cursor.execute(
					"INSERT OR REPLACE INTO cache (session, name, username, spamblock, task) VALUES (?, ?, ?, ?, ?)",
					(session, name, me.username, table[session]["spamblock"], "")
				)

				connection.commit()
				connection.close()
				await client.disconnect()
				
				console.log(f"Disconnected from [bold]{session}[/bold]")
				console.print()

			try:
				client.loop.run_until_complete(main())
			except RPCError as error:
				if error.message == "FROZEN_METHOD_INVALID":
					console.log("Frozen!")
					
					table[session]["frozen"] = True
				else:
					raise

	client = TelegramClient(os.path.join(config.sessions, config.worker), config.API_ID, config.API_HASH, system_version="5.9")

	async def main():
		message = await client.get_messages(PeerChannel(config.channel), ids=config.message)
		
		console.log(f"Updating table...")

		text = ""

		for session, data in table.items():
			if data:
				name = html.escape(data["name"])
				username = html.escape(data["username"])

				if "frozen" in data and data["frozen"]:
					text += f"<a href=\"https://t.me/{username}\">{name}</a> — <b>заморожен</b> ❄"
				else:
					spamblock = html.escape(data["spamblock"])
					task = html.escape(data["task"] or "")

					text += f"<a href=\"https://t.me/{username}\">{name}</a> — спамблок <b>{spamblock}</b>"
					if task: text += f" (в работе: <b>{task}</b>)"
			else:
				text += f"{session} (в работе)"

			text += "\n"

		strfnow = datetime.now().strftime("%H:%M:%S %d.%m.%Y")

		full_text = "\n\n".join([
			"<b>Таблица сессий</b>",
			text.strip(),
			f"Всего (так сказать, тотал): <code>{len(table)}</code>",
			f"Обновлено в <code>{strfnow}</code> (каждые <code>{config.interval}</code> минут)"
		])

		await message.edit(
			full_text,
			parse_mode="html"
		)

		console.log(f"Updated table")
		console.print()
	
	console.log(f"Logging in as [bold]{config.worker}[/bold]...")

	with client:
		client.loop.run_until_complete(main())
				
	console.log(f"Sleeping for [bold]{config.interval}[/bold] minutes...")

	time.sleep(config.interval * 60)

	console.log("Woke up")
	console.print()