"""CLI do sluice: shrink, recall, compress, report, bench, demo."""

import argparse
import glob
import os
import subprocess
import sys

from .context import Context
from .compressors.base import HANDLE_TOKEN
from .compressors.registry import compress as compress_text
from .estimator import estimate_tokens, savings_pct
from .store import Store


def _footer(name: str, ot: int, ct: int, handle: str) -> str:
    pct = savings_pct(ot, ct)
    return f"[sluice] {name}: {ot}->{ct} tokens (-{pct:.0f}%) · original: sluice recall {handle}"


def _emit(text: str, stream=sys.stdout) -> None:
    stream.write(text)
    if not text.endswith("\n"):
        stream.write("\n")


def cmd_shrink(args) -> int:
    if not args.command:
        sys.stderr.write("uso: sluice shrink -- <comando> [args...]\n")
        return 2
    store = Store()
    ctx = Context.from_cmdline(args.command, source="shell")
    try:
        proc = subprocess.run(
            args.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        sys.stderr.write(f"comando nao encontrado: {args.command[0]}\n")
        return 127
    original = proc.stdout or ""
    name, compressed = compress_text(original, ctx)
    handle = store.save_original(original)
    compressed = compressed.replace(HANDLE_TOKEN, handle)
    ot, ct = estimate_tokens(original), estimate_tokens(compressed)
    store.log_event(
        source="shell", command=ctx.command, compressor=name,
        orig_tokens=ot, comp_tokens=ct,
        orig_bytes=len(original.encode("utf-8", "replace")),
        comp_bytes=len(compressed.encode("utf-8", "replace")),
        handle=handle,
    )
    _emit(compressed, sys.stdout)
    sys.stderr.write("\n" + _footer(name, ot, ct, handle) + "\n")
    return proc.returncode


def cmd_compress(args) -> int:
    store = Store()
    if args.file and args.file != "-":
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        source = "file"
    else:
        text = sys.stdin.read()
        source = "stdin"
    if args.cmd:
        ctx = Context.from_cmdline(args.cmd.split(), source=source)
    else:
        ctx = Context(source=source)
    name, compressed = compress_text(text, ctx)
    handle = store.save_original(text)
    compressed = compressed.replace(HANDLE_TOKEN, handle)
    ot, ct = estimate_tokens(text), estimate_tokens(compressed)
    store.log_event(
        source=source, command=ctx.command, compressor=name,
        orig_tokens=ot, comp_tokens=ct,
        orig_bytes=len(text.encode("utf-8", "replace")),
        comp_bytes=len(compressed.encode("utf-8", "replace")),
        handle=handle,
    )
    _emit(compressed, sys.stdout)
    sys.stderr.write(_footer(name, ot, ct, handle) + "\n")
    return 0


def cmd_recall(args) -> int:
    store = Store()
    content = store.recall(args.handle)
    if content is None:
        sys.stderr.write(f"handle nao encontrado: {args.handle}\n")
        return 1
    _emit(content, sys.stdout)
    return 0


def cmd_report(args) -> int:
    store = Store()
    count, ot, ct, ob, cb = store.totals()
    print("== sluice report (estimativa inferida de tokens) ==")
    if not count:
        print("sem eventos ainda. Rode 'sluice shrink' ou 'sluice compress' primeiro.")
        return 0
    print(f"eventos           : {count}")
    print(f"tokens (orig)     : {ot}")
    print(f"tokens (comprim.) : {ct}")
    print(f"economia tokens   : {ot - ct}  (-{savings_pct(ot, ct):.1f}%)")
    print(f"bytes   economia  : {ob - cb}  (-{savings_pct(ob, cb):.1f}%)")
    print("\n-- por compressor --")
    for comp, n, go, gc in store.by_group("compressor"):
        print(f"  {comp:10} n={n:<4} {go}->{gc}  (-{savings_pct(go, gc):.0f}%)")
    print("\n-- por comando --")
    for cmd, n, go, gc in store.by_group("command"):
        label = (cmd or "(payload)")[:40]
        print(f"  {label:42} n={n:<4} {go}->{gc}  (-{savings_pct(go, gc):.0f}%)")
    print(
        "\nNota: a porcentagem OFICIAL deve vir dos tokens de entrada reportados pelo "
        "provedor. Esta tabela usa estimativa interna (ver PROPOSTA)."
    )
    return 0


def cmd_bench(args) -> int:
    files = sorted(
        p for p in glob.glob(os.path.join(args.dir, "*")) if os.path.isfile(p)
    )
    if not files:
        sys.stderr.write(f"nenhum arquivo em {args.dir}\n")
        return 1
    tot_o = tot_c = 0
    print(f"{'arquivo':28} {'compressor':11} {'orig':>7} {'comp':>7} {'economia':>9}")
    print("-" * 66)
    for path in files:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        stem = os.path.splitext(os.path.basename(path))[0]
        cmdline = stem.replace("__", " ")
        ctx = Context.from_cmdline(cmdline.split(), source="file")
        name, compressed = compress_text(text, ctx)
        ot, ct = estimate_tokens(text), estimate_tokens(compressed)
        tot_o += ot
        tot_c += ct
        print(
            f"{os.path.basename(path):28} {name:11} {ot:>7} {ct:>7} "
            f"{'-' + format(savings_pct(ot, ct), '.0f') + '%':>9}"
        )
    print("-" * 66)
    print(
        f"{'TOTAL':28} {'':11} {tot_o:>7} {tot_c:>7} "
        f"{'-' + format(savings_pct(tot_o, tot_c), '.0f') + '%':>9}"
    )
    return 0


def cmd_demo(args) -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    args.dir = os.path.join(here, "examples")
    return cmd_bench(args)


def cmd_proxy(args) -> int:
    from .proxy import DEFAULT_UPSTREAM, run_proxy

    store = None if args.no_store else Store()
    upstream = args.upstream or os.environ.get("SLUICE_UPSTREAM") or DEFAULT_UPSTREAM
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        sys.stderr.write(
            "[sluice] AVISO: escutar fora de 127.0.0.1 expoe um proxy que carrega "
            "a sua API key. Garanta protecao de rede.\n"
        )
    return run_proxy(
        host=args.host, port=args.port, upstream=upstream,
        store=store, verbose=args.verbose,
    )


def cmd_claude(args) -> int:
    base = f"http://{args.host}:{args.port}"
    print("# 1) suba o proxy em um terminal:")
    print(f"sluice proxy --host {args.host} --port {args.port}")
    print("# 2) em outro terminal, aponte o Claude Code (ou cliente Anthropic) para ele:")
    print(f"export ANTHROPIC_BASE_URL={base}")
    print("# sua ANTHROPIC_API_KEY continua no cliente e e repassada ao provedor.")
    print(f"# saude do proxy: curl {base}/__sluice__/health")
    print(f"# economia:       curl {base}/__sluice__/stats")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sluice",
        description="Sluice de compressao de contexto entre seus prompts e a IA.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shrink", help="roda um comando e comprime a saida")
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- <comando> [args]")
    s.set_defaults(func=cmd_shrink)

    c = sub.add_parser("compress", help="comprime um arquivo ou stdin")
    c.add_argument("file", nargs="?", default="-", help="arquivo ou '-' para stdin")
    c.add_argument("--cmd", help="dica de comando de origem, ex. 'git status'")
    c.set_defaults(func=cmd_compress)

    r = sub.add_parser("recall", help="recupera o original byte-a-byte por handle")
    r.add_argument("handle")
    r.set_defaults(func=cmd_recall)

    rep = sub.add_parser("report", help="mostra economia agregada do store")
    rep.set_defaults(func=cmd_report)

    b = sub.add_parser("bench", help="comprime todos os arquivos de um diretorio")
    b.add_argument("dir")
    b.set_defaults(func=cmd_bench)

    d = sub.add_parser("demo", help="roda o bench nos exemplos embutidos")
    d.set_defaults(func=cmd_demo)

    px = sub.add_parser("proxy", help="sobe o proxy local entre o cliente e o provedor")
    px.add_argument("--host", default="127.0.0.1")
    px.add_argument("--port", type=int, default=8787)
    px.add_argument("--upstream", default=None,
                    help="base do provedor (default https://api.anthropic.com)")
    px.add_argument("--no-store", action="store_true",
                    help="nao persistir originais/medicao")
    px.add_argument("-v", "--verbose", action="store_true")
    px.set_defaults(func=cmd_proxy)

    cl = sub.add_parser("claude", help="mostra como apontar o Claude Code para o sluice")
    cl.add_argument("--host", default="127.0.0.1")
    cl.add_argument("--port", type=int, default=8787)
    cl.set_defaults(func=cmd_claude)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # shrink usa REMAINDER; remove o '--' inicial se presente
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.func(args)
