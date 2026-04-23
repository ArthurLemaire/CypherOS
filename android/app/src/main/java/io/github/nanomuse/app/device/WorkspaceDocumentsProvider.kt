package io.github.nanomuse.app.device

import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.DocumentsProvider
import android.webkit.MimeTypeMap
import io.github.nanomuse.app.BuildConfig
import io.github.nanomuse.app.Prefs
import io.github.nanomuse.app.R
import io.github.nanomuse.app.runtime.LocalRuntime
import java.io.File
import java.io.FileNotFoundException

/**
 * The agent's workspace in the system Files app and in every "open" / "save" dialog on the
 * phone (Storage Access Framework): what nanoMuse made is a folder like any other, and a
 * file dropped there is in the workspace. Only when nanoMuse runs on this phone — the
 * connect build has no workspace here and shows no root.
 */
class WorkspaceDocumentsProvider : DocumentsProvider() {
    private val root: File? get() {
        val ctx = context ?: return null
        if (!BuildConfig.LOCAL_RUNTIME || !Prefs(ctx).isLocal) return null
        return File(LocalRuntime(ctx).home, "workspace").takeIf { it.isDirectory }
    }

    override fun onCreate(): Boolean = true

    override fun queryRoots(projection: Array<out String>?): Cursor {
        val cursor = MatrixCursor(projection ?: ROOT_COLUMNS)
        val dir = root ?: return cursor
        val ctx = context!!
        cursor.newRow()
            .add(DocumentsContract.Root.COLUMN_ROOT_ID, ROOT_ID)
            .add(DocumentsContract.Root.COLUMN_DOCUMENT_ID, id(dir))
            .add(DocumentsContract.Root.COLUMN_TITLE, Prefs(ctx).agentName.ifEmpty { ctx.getString(R.string.app_name) })
            .add(DocumentsContract.Root.COLUMN_SUMMARY, ctx.getString(R.string.documents_summary))
            .add(DocumentsContract.Root.COLUMN_FLAGS, DocumentsContract.Root.FLAG_SUPPORTS_CREATE or DocumentsContract.Root.FLAG_SUPPORTS_IS_CHILD or DocumentsContract.Root.FLAG_LOCAL_ONLY)
            .add(DocumentsContract.Root.COLUMN_ICON, R.mipmap.ic_launcher)
            .add(DocumentsContract.Root.COLUMN_MIME_TYPES, "*/*")
            .add(DocumentsContract.Root.COLUMN_AVAILABLE_BYTES, dir.usableSpace)
        return cursor
    }

    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor {
        val cursor = MatrixCursor(projection ?: DOC_COLUMNS)
        row(cursor, file(documentId))
        return cursor
    }

    override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor {
        val cursor = MatrixCursor(projection ?: DOC_COLUMNS)
        val parent = file(parentDocumentId)
        val children = parent.listFiles()?.filter { !it.name.startsWith(".") && it.name != "browser-profile" }?.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() })) ?: emptyList()
        for (f in children) row(cursor, f)
        return cursor
    }

    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
        val f = file(documentId)
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.parseMode(mode))
    }

    override fun createDocument(parentDocumentId: String, mimeType: String, displayName: String): String {
        val parent = file(parentDocumentId)
        val safe = displayName.replace('/', '_').trim().ifEmpty { "untitled" }
        var target = File(parent, safe)
        var n = 2
        while (target.exists()) { target = File(parent, "${safe.substringBeforeLast('.')} ($n)" + safe.substringAfterLast('.', "").let { if (it.isEmpty()) "" else ".$it" }); n++ }
        val ok = if (mimeType == DocumentsContract.Document.MIME_TYPE_DIR) target.mkdir() else target.createNewFile()
        if (!ok) throw FileNotFoundException("could not create $safe")
        return id(target)
    }

    override fun deleteDocument(documentId: String) {
        val f = file(documentId)
        if (f == root) throw UnsupportedOperationException("the workspace itself stays")
        if (!f.deleteRecursively()) throw FileNotFoundException("could not delete $documentId")
    }

    override fun renameDocument(documentId: String, displayName: String): String {
        val f = file(documentId)
        val target = File(f.parentFile, displayName.replace('/', '_'))
        if (target.exists() || !f.renameTo(target)) throw FileNotFoundException("could not rename to $displayName")
        return id(target)
    }

    override fun getDocumentType(documentId: String): String = mime(file(documentId))

    override fun isChildDocument(parentDocumentId: String, documentId: String): Boolean =
        documentId.startsWith(parentDocumentId.trimEnd('/') + "/") || documentId == parentDocumentId

    // ------------------------------------------------------------------ helpers

    private fun row(cursor: MatrixCursor, f: File) {
        var flags = 0
        if (f.isDirectory) flags = flags or DocumentsContract.Document.FLAG_DIR_SUPPORTS_CREATE
        else flags = flags or DocumentsContract.Document.FLAG_SUPPORTS_WRITE
        if (f != root) flags = flags or DocumentsContract.Document.FLAG_SUPPORTS_DELETE or DocumentsContract.Document.FLAG_SUPPORTS_RENAME
        cursor.newRow()
            .add(DocumentsContract.Document.COLUMN_DOCUMENT_ID, id(f))
            .add(DocumentsContract.Document.COLUMN_DISPLAY_NAME, if (f == root) context!!.getString(R.string.documents_root) else f.name)
            .add(DocumentsContract.Document.COLUMN_MIME_TYPE, mime(f))
            .add(DocumentsContract.Document.COLUMN_SIZE, if (f.isDirectory) null else f.length())
            .add(DocumentsContract.Document.COLUMN_LAST_MODIFIED, f.lastModified())
            .add(DocumentsContract.Document.COLUMN_FLAGS, flags)
    }

    /** Document ids are paths relative to the workspace, `.` for the workspace itself. */
    private fun id(f: File): String {
        val base = root ?: throw FileNotFoundException("no workspace")
        val rel = f.canonicalFile.relativeTo(base.canonicalFile).path
        return rel.ifEmpty { "." }
    }

    private fun file(documentId: String): File {
        val base = root ?: throw FileNotFoundException("no workspace on this phone")
        val f = if (documentId == "." || documentId.isEmpty()) base else File(base, documentId)
        val canonical = f.canonicalFile
        if (!canonical.path.startsWith(base.canonicalFile.path)) throw FileNotFoundException("outside the workspace")
        if (!canonical.exists()) throw FileNotFoundException(documentId)
        return canonical
    }

    private fun mime(f: File): String {
        if (f.isDirectory) return DocumentsContract.Document.MIME_TYPE_DIR
        val ext = f.extension.lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: when (ext) {
            "md" -> "text/markdown"; "toml", "yaml", "yml", "log" -> "text/plain"; "ics" -> "text/calendar"; "vcf" -> "text/vcard"
            else -> "application/octet-stream"
        }
    }

    companion object {
        private const val ROOT_ID = "workspace"
        private val ROOT_COLUMNS = arrayOf(
            DocumentsContract.Root.COLUMN_ROOT_ID, DocumentsContract.Root.COLUMN_DOCUMENT_ID, DocumentsContract.Root.COLUMN_TITLE, DocumentsContract.Root.COLUMN_SUMMARY,
            DocumentsContract.Root.COLUMN_FLAGS, DocumentsContract.Root.COLUMN_ICON, DocumentsContract.Root.COLUMN_MIME_TYPES, DocumentsContract.Root.COLUMN_AVAILABLE_BYTES,
        )
        private val DOC_COLUMNS = arrayOf(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_FLAGS,
        )
    }
}
