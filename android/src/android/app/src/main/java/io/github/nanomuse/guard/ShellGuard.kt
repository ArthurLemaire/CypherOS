package io.github.nanomuse.guard

/**
 * Classifies a shell command before it runs in the sandbox. Port of the Python line's
 * `nanomuse/tools/shell.py` + `sentinel/policy.py`, reshaped around the four questions the
 * app asks: does it delete, does it send, does it pay, does it install.
 *
 * The command is split into pipelines (`;`, `&&`, `||`, newlines) and each pipeline into
 * simple commands (`|`), respecting quotes. Each simple command is judged on its program
 * and arguments; the strongest verdict wins. Inline scripts (`sh -c`, `python -c`, heredocs
 * fed to a shell) are judged recursively or by content.
 *
 * The cwd of every agent shell is the session workspace, so relative paths are the user's
 * files. Scratch space (`/tmp`, `/var/tmp`, `/dev/shm`) is free to delete.
 */
object ShellGuard {
    const val WORKSPACE = "/var/minis/workspace"
    const val SHARED = "/var/minis/shared"

    private val scratchPrefixes = listOf("/tmp/", "/var/tmp/", "/dev/shm/", "\$TMPDIR/", "\${TMPDIR}/")
    private val wrappers = setOf("sudo", "doas", "nohup", "exec", "time", "env", "command", "busybox", "nice", "ionice", "stdbuf", "unbuffer")
    private val shells = setOf("sh", "bash", "ash", "dash", "zsh", "ksh", "fish")
    private val interpreters = setOf("python", "python3", "python2", "perl", "ruby", "node", "nodejs", "php", "lua")
    private val readOnlyVerbs = Regex("^\\+?(list|ls|get|search|read|show|status|help|download|fetch|export|whoami|agenda|consume|view|info|cat|describe|check|history|query|find|stat|watch|tail|log|logs|diff|open|print|version|doctor)(\\b|$)", RegexOption.IGNORE_CASE)
    private val moneyWords = Regex("(\\bpay\\b|payment|checkout|purchase|\\border\\b|transfer|alipay|wxpay|wechatpay|weixin.?pay|stripe|paypal|billing|subscribe|topup|top-up|recharge|refund|支付|付款|下单|转账|充值|购买|结算|退款)", RegexOption.IGNORE_CASE)
    private val dataFlags = setOf("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "-F", "--form", "--form-string", "--json", "-T", "--upload-file", "--post-data", "--post-file", "--body", "--body-file", "-I")
    private val writeMethods = setOf("POST", "PUT", "PATCH", "DELETE")
    private val urlRegex = Regex("https?://([^/\\s:'\"]+)", RegexOption.IGNORE_CASE)
    private val hostArg = Regex("^(?:[\\w.-]+@)?([\\w.-]+\\.[a-z]{2,}|\\d{1,3}(?:\\.\\d{1,3}){3}|[\\w-]+)(?::|$)", RegexOption.IGNORE_CASE)

    // Always-ask patterns, whatever else the command looks like.
    private val warningPatterns: List<Pair<Regex, String>> = listOf(
        Regex("\\bmkfs\\b|\\bdd\\s+(if|of)=") to "disk-level operation",
        Regex(">\\s*/dev/(sd|nvme|mmcblk|block)") to "writes to a block device",
        Regex("\\b(shutdown|reboot|halt|poweroff)\\b") to "system-level command",
        Regex("\\bchmod\\s+(-R\\s+)?(777|a\\+rwx)\\b|\\bchmod\\s+-R\\s+.*\\s/(\\s|$)") to "world-writable permissions",
        Regex("\\bgit\\s+push\\b[^;&|]*(--force\\b|\\s-f\\b|--force-with-lease|\\s\\+\\S)") to "force push",
        Regex(":\\(\\)\\s*\\{\\s*:\\s*\\|\\s*:\\s*&\\s*\\}\\s*;\\s*:") to "fork bomb",
        Regex("\\bcurl\\b[^|]*\\|\\s*(sudo\\s+)?(ba|z|a|da)?sh\\b|\\bwget\\b[^|]*\\|\\s*(sudo\\s+)?(ba|z|a|da)?sh\\b") to "pipes a download into a shell",
        Regex("\\bcurl\\b[^|]*\\|\\s*(python3?|perl|node)\\b|\\bwget\\b[^|]*\\|\\s*(python3?|perl|node)\\b") to "pipes a download into an interpreter",
    )

    // Inline-code reach, for `python -c`, `node -e`, heredocs.
    private val codeDeletes = Regex("\\b(shutil\\.rmtree|os\\.(remove|unlink|rmdir|removedirs)|pathlib\\.[^\\n]*\\.unlink|\\.unlink\\(|fs\\.(rm|rmSync|rmdir|rmdirSync|unlink|unlinkSync)|rimraf|File\\.delete|FileUtils\\.rm)\\b")
    private val codeSends = Regex("\\b(requests\\.(post|put|patch|delete)|urllib\\.request\\.urlopen\\([^)]*data|httpx\\.(post|put|patch|delete)|aiohttp[^\\n]*\\.(post|put)|smtplib|sendmail|axios\\.(post|put|patch|delete)|fetch\\([^)]*method\\s*:\\s*['\"](POST|PUT|PATCH|DELETE)|nodemailer|twilio|SendGrid|boto3[^\\n]*\\.(put_object|send_email|publish)|lark|feishu|dingtalk|wecom|telegram|slack_sdk)\\b", RegexOption.IGNORE_CASE)
    private val codeInstalls = Regex("\\b(pip\\.main|subprocess[^\\n]*(pip|apk|apt|npm)\\s+(install|add))\\b")

    fun assess(command: String): RiskAssessment = assess(command, depth = 0)

    private fun assess(command: String, depth: Int): RiskAssessment {
        if (depth > 3 || command.isBlank()) return RiskAssessment.SAFE
        var result = RiskAssessment.SAFE
        val warnings = warningPatterns.filter { it.first.containsMatchIn(command) }.map { it.second }
        if (warnings.isNotEmpty()) {
            // A pipe into a shell is an install by shape; the warning makes it ask anyway.
            val cls = if (warnings.any { it.startsWith("pipes a download") }) RiskClass.INSTALL else RiskClass.DESTRUCTIVE
            result = RiskAssessment(cls, warnings.joinToString("; "), warnings = warnings)
        }
        for (pipeline in splitPipelines(command)) {
            for (simple in splitPipes(pipeline)) {
                result = RiskAssessment.merge(result, assessSimple(simple, depth))
            }
        }
        return result
    }

    // ── one simple command ─────────────────────────────────────────────────────────────────

    private fun assessSimple(text: String, depth: Int): RiskAssessment {
        val heredoc = Regex("<<-?\\s*['\"]?(\\w+)['\"]?\\s*\\n").find(text)
        val head = if (heredoc != null) text.substring(0, heredoc.range.first) else text
        val body = if (heredoc != null) text.substring(heredoc.range.last + 1).substringBefore("\n" + heredoc.groupValues[1]) else null

        var tokens = tokenize(head)
        // Drop env assignments and wrappers to reach the real program.
        while (tokens.isNotEmpty() && (Regex("^[A-Za-z_][A-Za-z0-9_]*=").containsMatchIn(tokens[0]) || basename(tokens[0]) in wrappers)) {
            if (basename(tokens[0]) == "timeout" || basename(tokens[0]) == "nice") tokens = tokens.drop(1)
            tokens = tokens.drop(1)
            if (tokens.isNotEmpty() && basename(tokens.getOrNull(0) ?: "") == "timeout") tokens = tokens.drop(2)
        }
        if (tokens.isEmpty()) return if (body != null) assessInline(body, depth) else RiskAssessment.SAFE
        val program = basename(tokens[0])
        val args = tokens.drop(1)

        val fromBody = if (body != null && (program in shells || program in interpreters)) assessInline(body, depth) else RiskAssessment.SAFE
        val own = when {
            program in shells -> shellWrapper(args, depth)
            program in interpreters -> interpreterInline(args, depth)
            program == "xargs" -> assessSimple(args.dropWhile { it.startsWith("-") }.joinToString(" ") + " ?", depth)
            program == "rm" -> rm(args)
            program == "find" -> find(args)
            program in setOf("shred", "wipe", "srm") -> RiskAssessment(RiskClass.DESTRUCTIVE, "destroys files", folderOf(args.lastOrNull { !it.startsWith("-") }))
            program == "truncate" -> RiskAssessment(RiskClass.DESTRUCTIVE, "empties a file", folderOf(args.lastOrNull { !it.startsWith("-") }))
            program == "crontab" && "-r" in args -> RiskAssessment(RiskClass.DESTRUCTIVE, "removes all scheduled jobs", "crontab")
            program == "git" -> git(args)
            program in setOf("curl", "wget", "http", "https", "xh", "httpie") -> httpClient(program, args)
            program in setOf("ssh", "scp", "sftp", "rsync", "ftp", "lftp", "telnet", "nc", "ncat", "netcat", "socat") -> remote(program, args)
            program in setOf("mail", "mailx", "sendmail", "msmtp", "mutt", "neomutt", "swaks", "ssmtp", "s-nail") -> RiskAssessment(RiskClass.OUTBOUND, "sends an email", args.firstOrNull { it.contains("@") } ?: "email")
            program == "lark-cli" || program == "lark" || program == "feishu" || program == "feishu-cli" -> larkCli(program, args)
            program == "gh" -> gh(args)
            program in setOf("aws", "gcloud", "az", "oss", "ossutil", "coscli", "qshell", "rclone") -> cloudCli(program, args)
            program in setOf("twine", "npm", "pnpm", "yarn", "cargo", "gem", "docker", "podman", "flyctl", "vercel", "netlify", "wrangler", "heroku") -> publishOrInstall(program, args)
            program in setOf("apk", "apt", "apt-get", "dnf", "yum", "pacman", "zypper", "pip", "pip3", "pipx", "uv", "brew", "conda", "mamba", "go", "npx", "bunx", "pnpx", "gem", "cpan", "cpanm", "luarocks", "opam", "nix-env") -> installer(program, args)
            program == "minis-config" -> RiskAssessment.SAFE // has its own confirmation sheet
            Regex("(send|notify|sms|push|mailer|telegram|whatsapp|wechat|weixin|dingtalk|wecom|slack|discord|twilio|pushover|bark|ntfy)", RegexOption.IGNORE_CASE).containsMatchIn(program) &&
                program !in setOf("notify-send") -> RiskAssessment(RiskClass.OUTBOUND, "$program sends a message", program)
            else -> RiskAssessment.SAFE
        }
        val merged = RiskAssessment.merge(own, fromBody)
        // Money words on an outbound call make it a payment.
        return if (merged.riskClass == RiskClass.OUTBOUND && moneyWords.containsMatchIn(text)) {
            merged.copy(riskClass = RiskClass.MONEY, reason = "looks like a payment: " + merged.reason)
        } else merged
    }

    private fun shellWrapper(args: List<String>, depth: Int): RiskAssessment {
        val i = args.indexOfFirst { it == "-c" || it == "-lc" || it == "-ec" || it == "-euc" }
        if (i >= 0 && i + 1 < args.size) return assess(args[i + 1], depth + 1)
        return RiskAssessment.SAFE // running a script file: judged by what the file does when it runs
    }

    private fun interpreterInline(args: List<String>, depth: Int): RiskAssessment {
        val i = args.indexOfFirst { it == "-c" || it == "-e" || it == "--eval" || it == "-r" }
        if (i >= 0 && i + 1 < args.size) return assessInline(args[i + 1], depth)
        // `python -m pip install`, `python -m twine upload`
        val m = args.indexOf("-m")
        if (m >= 0 && m + 1 < args.size) return assessSimple((listOf(args[m + 1]) + args.drop(m + 2)).joinToString(" ") { quote(it) }, depth)
        return RiskAssessment.SAFE
    }

    /** Inline code: judged by what it can reach, not by parsing it. */
    private fun assessInline(code: String, depth: Int): RiskAssessment {
        var r = RiskAssessment.SAFE
        // A heredoc or -c string that is itself shell gets the full treatment.
        if (Regex("(^|\\n|;|&&)\\s*(rm|curl|wget|git|apk|apt|pip|npm|find|lark-cli|gh|ssh|scp|rsync)\\b").containsMatchIn(code)) {
            r = RiskAssessment.merge(r, assess(code, depth + 1))
        }
        if (codeDeletes.containsMatchIn(code)) r = RiskAssessment.merge(r, RiskAssessment(RiskClass.DESTRUCTIVE, "code deletes files", null))
        if (codeSends.containsMatchIn(code)) {
            val host = urlRegex.find(code)?.groupValues?.get(1)
            r = RiskAssessment.merge(r, RiskAssessment(RiskClass.OUTBOUND, "code sends data" + (host?.let { " to $it" } ?: ""), host))
        }
        if (codeInstalls.containsMatchIn(code)) r = RiskAssessment.merge(r, RiskAssessment(RiskClass.INSTALL, "code installs packages", null))
        if (r.riskClass == RiskClass.OUTBOUND && moneyWords.containsMatchIn(code)) r = r.copy(riskClass = RiskClass.MONEY, reason = "looks like a payment: " + r.reason)
        return r
    }

    // ── programs ───────────────────────────────────────────────────────────────────────────

    private fun rm(args: List<String>): RiskAssessment {
        val targets = positional(args)
        if (targets.isEmpty()) return RiskAssessment.SAFE
        val resolved = targets.map { resolve(it) }
        val whole = resolved.filter { isWholeTree(it) }
        if (whole.isNotEmpty()) {
            return RiskAssessment(RiskClass.DESTRUCTIVE, "removes ${whole.first()} entirely", folderOf(whole.first()), warnings = listOf("wipes ${whole.first()}"))
        }
        val kept = resolved.filterNot { isScratch(it) }
        if (kept.isEmpty()) return RiskAssessment.SAFE
        val shown = kept.take(3).joinToString(", ") + if (kept.size > 3) " …" else ""
        return RiskAssessment(RiskClass.DESTRUCTIVE, "deletes $shown", folderOf(kept.first()))
    }

    private fun find(args: List<String>): RiskAssessment {
        val deletes = "-delete" in args || args.zipWithNext().any { (a, b) -> (a == "-exec" || a == "-execdir" || a == "-ok") && basename(b) == "rm" } ||
            args.zipWithNext().any { (a, b) -> a == "-exec" && basename(b) == "shred" }
        if (!deletes) return RiskAssessment.SAFE
        val start = resolve(args.firstOrNull { !it.startsWith("-") } ?: ".")
        if (isScratch(start)) return RiskAssessment.SAFE
        return RiskAssessment(RiskClass.DESTRUCTIVE, "deletes files under $start", folderOf(start))
    }

    private fun git(args: List<String>): RiskAssessment {
        val sub = args.firstOrNull { !it.startsWith("-") } ?: return RiskAssessment.SAFE
        val rest = args.drop(args.indexOf(sub) + 1)
        return when (sub) {
            "push" -> {
                val remote = rest.firstOrNull { !it.startsWith("-") && !it.startsWith("+") } ?: "origin"
                RiskAssessment(RiskClass.OUTBOUND, "pushes to $remote", "git:$remote")
            }
            "clean" -> if (rest.any { it.startsWith("-") && (it.contains('f') || it == "--force") }) RiskAssessment(RiskClass.DESTRUCTIVE, "git clean removes untracked files", WORKSPACE) else RiskAssessment.SAFE
            "reset" -> if ("--hard" in rest) RiskAssessment(RiskClass.DESTRUCTIVE, "git reset --hard discards changes", WORKSPACE) else RiskAssessment.SAFE
            "checkout", "restore" -> if (rest.any { it == "--" || it == "." } || (sub == "restore" && rest.isNotEmpty() && rest.none { it.startsWith("--staged") })) RiskAssessment(RiskClass.DESTRUCTIVE, "git $sub discards working changes", WORKSPACE) else RiskAssessment.SAFE
            "branch" -> if ("-D" in rest || "--delete" in rest && "--force" in rest) RiskAssessment(RiskClass.DESTRUCTIVE, "force-deletes a branch", WORKSPACE) else RiskAssessment.SAFE
            "stash" -> if (rest.firstOrNull() in setOf("drop", "clear")) RiskAssessment(RiskClass.DESTRUCTIVE, "drops stashed changes", WORKSPACE) else RiskAssessment.SAFE
            else -> RiskAssessment.SAFE
        }
    }

    private fun httpClient(program: String, args: List<String>): RiskAssessment {
        val host = args.firstNotNullOfOrNull { urlRegex.find(it)?.groupValues?.get(1) }
            ?: args.firstOrNull { !it.startsWith("-") && Regex("^[\\w.-]+\\.[a-z]{2,}(/|$)", RegexOption.IGNORE_CASE).containsMatchIn(it) }?.substringBefore("/")
        var method: String? = null
        var sendsData = false
        args.forEachIndexed { i, a ->
            when {
                a == "-X" || a == "--request" -> method = args.getOrNull(i + 1)?.uppercase()
                a.startsWith("--request=") -> method = a.substringAfter("=").uppercase()
                a.startsWith("--method=") -> method = a.substringAfter("=").uppercase()
                a.startsWith("-X") && a.length > 2 -> method = a.substring(2).uppercase()
                a in dataFlags && a != "-I" -> sendsData = true
                dataFlags.any { f -> f != "-I" && a.startsWith("$f=") } -> sendsData = true
                a.startsWith("-d") && a.length > 2 && !a.startsWith("--") -> sendsData = true
                a.startsWith("-F") && a.length > 2 && !a.startsWith("--") -> sendsData = true
            }
        }
        // httpie: `http POST host …` or `http host key=value`
        if (program in setOf("http", "https", "xh", "httpie")) {
            args.firstOrNull { it.uppercase() in writeMethods }?.let { method = it.uppercase() }
            if (args.any { !it.startsWith("-") && Regex("^[\\w-]+[:=]=?\\S").containsMatchIn(it) && !it.contains("://") }) sendsData = true
        }
        val writes = sendsData || method in writeMethods
        if (!writes) return RiskAssessment.SAFE
        return RiskAssessment(RiskClass.OUTBOUND, "${method ?: "POST"}s to ${host ?: "a server"}", host)
    }

    private fun remote(program: String, args: List<String>): RiskAssessment {
        val positional = positional(args)
        val remoteArg = positional.firstOrNull { it.contains(':') && !it.startsWith("/") && !Regex("^[A-Za-z]:\\\\").containsMatchIn(it) }
            ?: positional.firstOrNull { hostArg.containsMatchIn(it) && it != "localhost" }
        if (program == "rsync" && remoteArg == null) return RiskAssessment.SAFE
        if (remoteArg == null && program in setOf("nc", "ncat", "netcat", "socat")) return RiskAssessment.SAFE
        val host = remoteArg?.let { hostArg.find(it)?.groupValues?.get(1) ?: it.substringBefore(':') } ?: program
        val verb = when (program) { "ssh" -> "runs commands on"; "scp", "sftp", "rsync", "ftp", "lftp" -> "copies files to/from"; else -> "opens a connection to" }
        return RiskAssessment(RiskClass.OUTBOUND, "$verb $host", host)
    }

    private fun larkCli(program: String, args: List<String>): RiskAssessment {
        val plus = args.filter { it.startsWith("+") }
        val verbs = if (plus.isNotEmpty()) plus else positional(args).drop(1).take(1)
        if (verbs.isEmpty() || verbs.all { readOnlyVerbs.containsMatchIn(it) } || args.any { it == "--help" || it == "-h" }) return RiskAssessment.SAFE
        val domain = positional(args).firstOrNull() ?: "lark"
        val recipient = listOf("--chat-id", "--chat", "--to", "--receive-id", "--open-id", "--user", "--email", "--user-id", "--email-to").firstNotNullOfOrNull { f ->
            args.indexOf(f).takeIf { it >= 0 }?.let { args.getOrNull(it + 1) } ?: args.firstOrNull { it.startsWith("$f=") }?.substringAfter("=")
        }
        val target = recipient?.let { "lark:$it" } ?: "lark:$domain"
        return RiskAssessment(RiskClass.OUTBOUND, "$program ${verbs.joinToString(" ")} — writes to Lark/Feishu", target)
    }

    private fun gh(args: List<String>): RiskAssessment {
        val p = positional(args)
        val area = p.getOrNull(0) ?: return RiskAssessment.SAFE
        val verb = p.getOrNull(1)
        if (area == "api") {
            val writes = args.any { it == "-X" || it == "--method" || it == "-f" || it == "-F" || it == "--field" || it == "--raw-field" || it == "--input" } &&
                args.none { it.uppercase() == "GET" }
            return if (writes) RiskAssessment(RiskClass.OUTBOUND, "gh api writes to GitHub", "github.com") else RiskAssessment.SAFE
        }
        if (verb == null || readOnlyVerbs.containsMatchIn(verb) || verb in setOf("checkout", "clone")) return RiskAssessment.SAFE
        if (verb == "delete" && area in setOf("repo", "release", "secret", "gist", "cache")) return RiskAssessment(RiskClass.DESTRUCTIVE, "gh $area delete", "github.com")
        return RiskAssessment(RiskClass.OUTBOUND, "gh $area $verb writes to GitHub", "github.com")
    }

    private fun cloudCli(program: String, args: List<String>): RiskAssessment {
        val words = positional(args).map { it.lowercase() }
        if (words.isEmpty() || words.any { it in setOf("ls", "list", "describe", "get", "cat", "lsd", "size", "check", "version", "config", "help", "whoami", "stat", "info") } && words.none { it in setOf("cp", "sync", "mv", "rm", "delete", "put", "upload", "copy", "move", "purge", "publish", "send", "invoke") }) return RiskAssessment.SAFE
        val destructive = words.any { it in setOf("rm", "delete", "purge", "remove", "terminate", "destroy") }
        return if (destructive) RiskAssessment(RiskClass.DESTRUCTIVE, "$program deletes remote data", program)
        else RiskAssessment(RiskClass.OUTBOUND, "$program writes to the cloud", program)
    }

    private fun publishOrInstall(program: String, args: List<String>): RiskAssessment {
        val words = positional(args).map { it.lowercase() }
        val first = words.firstOrNull() ?: return RiskAssessment.SAFE
        return when {
            first in setOf("publish", "upload", "push", "deploy", "release") -> RiskAssessment(RiskClass.OUTBOUND, "$program $first publishes", program)
            program == "docker" || program == "podman" -> RiskAssessment.SAFE
            first in setOf("install", "i", "add", "ci", "update", "upgrade") -> RiskAssessment(RiskClass.INSTALL, "$program $first", program)
            else -> RiskAssessment.SAFE
        }
    }

    private fun installer(program: String, args: List<String>): RiskAssessment {
        val words = positional(args).map { it.lowercase() }
        return when (program) {
            "npx", "bunx", "pnpx" -> RiskAssessment(RiskClass.INSTALL, "$program downloads and runs a package", program)
            "go" -> if (words.firstOrNull() in setOf("install", "get")) RiskAssessment(RiskClass.INSTALL, "go ${words.first()}", "go") else RiskAssessment.SAFE
            "uv" -> if (words.take(2).any { it in setOf("add", "install", "sync") } || (words.getOrNull(0) == "tool" && words.getOrNull(1) in setOf("install", "run")) || words.getOrNull(0) == "pip" && words.getOrNull(1) == "install") RiskAssessment(RiskClass.INSTALL, "uv installs packages", "uv") else RiskAssessment.SAFE
            "pacman" -> if (args.any { it.startsWith("-S") }) RiskAssessment(RiskClass.INSTALL, "pacman installs packages", "pacman") else RiskAssessment.SAFE
            else -> if (words.firstOrNull() in setOf("add", "install", "reinstall", "upgrade", "update", "dist-upgrade", "full-upgrade")) RiskAssessment(RiskClass.INSTALL, "$program ${words.first()}", program) else RiskAssessment.SAFE
        }
    }

    // ── paths ──────────────────────────────────────────────────────────────────────────────

    private fun resolve(raw: String): String {
        var p = raw.trim().trim('"', '\'')
        if (p.startsWith("~")) p = "/root" + p.drop(1)
        if (p.startsWith("\$TMPDIR") || p.startsWith("\${TMPDIR}")) p = "/tmp" + p.removePrefix("\${TMPDIR}").removePrefix("\$TMPDIR")
        if (p == "\$HOME" || p.startsWith("\$HOME/")) p = "/root" + p.removePrefix("\$HOME")
        if (p.startsWith("\$PWD/")) p = WORKSPACE + p.removePrefix("\$PWD")
        if (!p.startsWith("/") && !p.startsWith("\$")) {
            p = if (p == "." || p == "./" || p == "*" || p == "./*") WORKSPACE else "$WORKSPACE/" + p.removePrefix("./")
        }
        // Collapse `a/b/..` a little so `/var/minis/workspace/x/..` is the workspace.
        val parts = ArrayList<String>()
        for (seg in p.split('/')) {
            when (seg) {
                "", "." -> {}
                ".." -> if (parts.isNotEmpty()) parts.removeAt(parts.size - 1)
                else -> parts.add(seg)
            }
        }
        return "/" + parts.joinToString("/")
    }

    private fun isScratch(path: String): Boolean =
        scratchPrefixes.any { path.startsWith(it) } || path in setOf("/tmp", "/var/tmp", "/dev/shm")

    /** The roots nobody deletes in one go. */
    private fun isWholeTree(path: String): Boolean = path in setOf(
        "/", "/root", "/home", "/etc", "/usr", "/var", "/bin", "/lib", "/opt", "/var/minis", WORKSPACE, SHARED, "/var/minis/skills", "/var/minis/attachments",
    ) || path == "/*"

    /** The folder a standing grant is bound to. */
    private fun folderOf(pathOrNull: String?): String? {
        val path = pathOrNull?.let { resolve(it) } ?: return null
        return when {
            path.startsWith("$WORKSPACE/") || path == WORKSPACE -> WORKSPACE
            path.startsWith("$SHARED/") || path == SHARED -> SHARED
            else -> {
                val parts = path.trim('/').split('/')
                if (parts.size <= 2) "/" + parts.joinToString("/") else "/" + parts.take(2).joinToString("/")
            }
        }
    }

    // ── tokenizing ─────────────────────────────────────────────────────────────────────────

    private fun positional(args: List<String>): List<String> {
        val out = ArrayList<String>()
        var passthrough = false
        for (a in args) {
            if (passthrough) { out.add(a); continue }
            if (a == "--") { passthrough = true; continue }
            if (a.startsWith("-") && a.length > 1) continue
            out.add(a)
        }
        return out
    }

    private fun basename(token: String): String = token.trim('"', '\'').substringAfterLast('/')

    private fun quote(s: String): String = if (s.any { it.isWhitespace() || it == '"' || it == '\'' }) "'" + s.replace("'", "'\\''") + "'" else s

    /** Splits on `;`, `&&`, `||` and newlines outside quotes. `|` is left for [splitPipes]. */
    internal fun splitPipelines(command: String): List<String> = splitOn(command) { s, i ->
        when {
            s[i] == '\n' || s[i] == ';' -> 1
            s.startsWith("&&", i) || s.startsWith("||", i) -> 2
            s[i] == '&' && (i + 1 >= s.length || s[i + 1] != '&') && (i == 0 || s[i - 1] != '>') -> 1
            else -> 0
        }
    }

    internal fun splitPipes(pipeline: String): List<String> = splitOn(pipeline) { s, i ->
        if (s[i] == '|' && (i + 1 >= s.length || s[i + 1] != '|') && (i == 0 || s[i - 1] != '|')) 1 else 0
    }

    private fun splitOn(text: String, sep: (String, Int) -> Int): List<String> {
        val out = ArrayList<String>()
        val cur = StringBuilder()
        var quote: Char? = null
        var depth = 0
        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (quote != null) {
                cur.append(c)
                if (c == '\\' && quote == '"' && i + 1 < text.length) { cur.append(text[i + 1]); i += 2; continue }
                if (c == quote) quote = null
                i++; continue
            }
            when {
                c == '\\' && i + 1 < text.length -> { cur.append(c).append(text[i + 1]); i += 2; continue }
                c == '\'' || c == '"' || c == '`' -> { quote = c; cur.append(c) }
                c == '(' -> { depth++; cur.append(c) }
                c == ')' -> { depth = (depth - 1).coerceAtLeast(0); cur.append(c) }
                depth == 0 -> {
                    val n = sep(text, i)
                    if (n > 0) { if (cur.isNotBlank()) out.add(cur.toString().trim()); cur.setLength(0); i += n; continue }
                    cur.append(c)
                }
                else -> cur.append(c)
            }
            i++
        }
        if (cur.isNotBlank()) out.add(cur.toString().trim())
        return out
    }

    /** A small shlex: quotes and backslashes, nothing else. Quotes are stripped. */
    internal fun tokenize(text: String): List<String> {
        val out = ArrayList<String>()
        val cur = StringBuilder()
        var quote: Char? = null
        var inToken = false
        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (quote != null) {
                if (c == quote) { quote = null }
                else if (c == '\\' && quote == '"' && i + 1 < text.length) { cur.append(text[i + 1]); i++ }
                else cur.append(c)
                i++; continue
            }
            when {
                c == '\'' || c == '"' -> { quote = c; inToken = true }
                c == '\\' && i + 1 < text.length -> { cur.append(text[i + 1]); inToken = true; i++ }
                c.isWhitespace() -> { if (inToken) { out.add(cur.toString()); cur.setLength(0); inToken = false } }
                else -> { cur.append(c); inToken = true }
            }
            i++
        }
        if (inToken) out.add(cur.toString())
        return out
    }
}
