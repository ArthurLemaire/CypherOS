package io.github.nanomuse.app.device

import android.Manifest
import android.content.Context
import android.net.Uri
import android.provider.ContactsContract
import io.github.nanomuse.app.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** The phone's address book, read-only: names, numbers, e-mail addresses. */
class ContactsTools(private val context: Context) {
    suspend fun search(query: String, limit: Int): JSONObject {
        val q = query.trim()
        if (q.isEmpty()) throw ToolError("give a name, a number or an address to look for")
        Ask.require(context, arrayOf(Manifest.permission.READ_CONTACTS), context.getString(R.string.ask_why_contacts), "read the contacts")
        val max = limit.coerceIn(1, 50)
        return withContext(Dispatchers.IO) {
            val ids = LinkedHashMap<Long, String>()
            // by name first, then anything whose number or address contains it
            val byName = Uri.withAppendedPath(ContactsContract.Contacts.CONTENT_FILTER_URI, Uri.encode(q))
            context.contentResolver.query(byName, arrayOf(ContactsContract.Contacts._ID, ContactsContract.Contacts.DISPLAY_NAME_PRIMARY), null, null, "${ContactsContract.Contacts.DISPLAY_NAME_PRIMARY} ASC")?.use { c ->
                while (c.moveToNext() && ids.size < max) ids[c.getLong(0)] = c.getString(1) ?: ""
            }
            if (ids.size < max) {
                val sel = "(${ContactsContract.Data.MIMETYPE} = ? OR ${ContactsContract.Data.MIMETYPE} = ?) AND ${ContactsContract.Data.DATA1} LIKE ?"
                val args = arrayOf(ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE, ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE, "%$q%")
                context.contentResolver.query(ContactsContract.Data.CONTENT_URI, arrayOf(ContactsContract.Data.CONTACT_ID, ContactsContract.Data.DISPLAY_NAME_PRIMARY), sel, args, null)?.use { c ->
                    while (c.moveToNext() && ids.size < max) ids.putIfAbsent(c.getLong(0), c.getString(1) ?: "")
                }
            }
            val people = JSONArray()
            for ((id, name) in ids) {
                people.put(
                    JSONObject()
                        .put("name", name)
                        .put("phones", details(id, ContactsContract.CommonDataKinds.Phone.CONTENT_URI, ContactsContract.CommonDataKinds.Phone.CONTACT_ID, ContactsContract.CommonDataKinds.Phone.NUMBER, ContactsContract.CommonDataKinds.Phone.TYPE, ::phoneType))
                        .put("emails", details(id, ContactsContract.CommonDataKinds.Email.CONTENT_URI, ContactsContract.CommonDataKinds.Email.CONTACT_ID, ContactsContract.CommonDataKinds.Email.ADDRESS, ContactsContract.CommonDataKinds.Email.TYPE, ::emailType)),
                )
            }
            JSONObject().put("query", q).put("count", people.length()).put("people", people)
        }
    }

    private fun details(contactId: Long, uri: Uri, idCol: String, valueCol: String, typeCol: String, label: (Int) -> String): JSONArray {
        val out = JSONArray()
        val seen = HashSet<String>()
        context.contentResolver.query(uri, arrayOf(valueCol, typeCol), "$idCol = ?", arrayOf(contactId.toString()), null)?.use { c ->
            while (c.moveToNext()) {
                val v = c.getString(0)?.trim().orEmpty()
                if (v.isEmpty() || !seen.add(v)) continue
                out.put(JSONObject().put("value", v).put("type", label(c.getInt(1))))
            }
        }
        return out
    }

    private fun phoneType(t: Int) = when (t) {
        ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE -> "mobile"
        ContactsContract.CommonDataKinds.Phone.TYPE_HOME -> "home"
        ContactsContract.CommonDataKinds.Phone.TYPE_WORK -> "work"
        ContactsContract.CommonDataKinds.Phone.TYPE_MAIN -> "main"
        else -> "other"
    }

    private fun emailType(t: Int) = when (t) {
        ContactsContract.CommonDataKinds.Email.TYPE_HOME -> "home"
        ContactsContract.CommonDataKinds.Email.TYPE_WORK -> "work"
        else -> "other"
    }
}
