package com.elysia.runtime

/**
 * Character-level tokenizer used by the bundled ULTRA_LIGHT model.
 * The vocabulary must match the model's training vocabulary.
 */
class CharTokenizer(private val vocab: List<Char>) {

    companion object {
        const val MAX_SEQ = 256
        const val CTX_WINDOW = 128
        const val PAD_ID = 0
        const val UNK_ID = 1
        const val EOS_ID = 2

        fun default(): CharTokenizer {
            val chars = mutableListOf('\u0000', '\u0001', '\u0002') // pad, unk, eos
            for (c in 32..126) chars.add(c.toChar())
            for (c in listOf('\n', '\t', '\r')) chars.add(c)
            return CharTokenizer(chars)
        }
    }

    private val idToChar = vocab.toCharArray()
    private val charToId: Map<Char, Int> = vocab.mapIndexed { i, c -> c to i }.toMap()

    val vocabSize: Int get() = vocab.size

    fun encode(text: String): List<Int> {
        return text.take(MAX_SEQ).map { charToId[it] ?: UNK_ID }
    }

    fun decode(ids: List<Int>): String {
        return buildString {
            ids.forEach { id ->
                if (id in idToChar.indices) append(idToChar[id])
            }
        }
    }

    fun decodeId(id: Int): Char {
        return if (id in idToChar.indices) idToChar[id] else '?'
    }
}
