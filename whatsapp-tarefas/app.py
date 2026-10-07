from bot import TaskStore, process_message


def main() -> None:
    store = TaskStore()
    pending_reminder_task: str | None = None

    print(
        "Bot de tarefas com Gemini. Escreva naturalmente; "
        "digite 'sair' para encerrar."
    )

    while True:
        try:
            message = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté mais!")
            break

        if not message:
            continue
        if message.casefold() in {"sair", "encerrar"}:
            print("Bot: Até mais!")
            break

        reply, pending_reminder_task = process_message(
            message,
            store,
            pending_reminder_task,
        )
        print(f"Bot: {reply}")


if __name__ == "__main__":
    main()
