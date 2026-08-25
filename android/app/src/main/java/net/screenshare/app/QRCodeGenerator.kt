package net.screenshare.app

import android.graphics.Bitmap
import android.graphics.Color
import kotlin.math.abs
import kotlin.math.max

object QRCodeGenerator {

    private val GF_EXP = IntArray(512)
    private val GF_LOG = IntArray(256)

    init {
        var x = 1
        for (i in 0 until 255) {
            GF_EXP[i] = x
            GF_EXP[i + 255] = x
            GF_LOG[x] = i
            x = x shl 1
            if ((x and 256) != 0) {
                x = x xor 0x11D
            }
        }
    }

    private fun gfMul(x: Int, y: Int): Int {
        if (x == 0 || y == 0) return 0
        return GF_EXP[GF_LOG[x] + GF_LOG[y]]
    }

    private fun rsGeneratorPoly(degree: Int): IntArray {
        var poly = intArrayOf(1)
        for (i in 0 until degree) {
            val nextPoly = IntArray(poly.size + 1)
            val root = GF_EXP[i]
            for (j in poly.indices) {
                nextPoly[j] = nextPoly[j] xor gfMul(poly[j], root)
                nextPoly[j + 1] = nextPoly[j + 1] xor poly[j]
            }
            poly = nextPoly
        }
        return poly
    }

    private fun rsEncode(data: IntArray, numEcBytes: Int): IntArray {
        val gen = rsGeneratorPoly(numEcBytes)
        val msg = IntArray(data.size + numEcBytes)
        System.arraycopy(data, 0, msg, 0, data.size)

        for (i in data.indices) {
            val coef = msg[i]
            if (coef != 0) {
                for (j in gen.indices) {
                    msg[i + j] = msg[i + j] xor gfMul(gen[j], coef)
                }
            }
        }

        val ec = IntArray(numEcBytes)
        System.arraycopy(msg, data.size, ec, 0, numEcBytes)
        return ec
    }

    private data class VersionSpec(
        val version: Int,
        val size: Int,
        val totalCodewords: Int,
        val dataCodewords: Int,
        val ecCodewords: Int,
        val alignment: IntArray
    )

    private val VERSION_SPECS = arrayOf(
        VersionSpec(1, 21, 26, 19, 7, intArrayOf()),
        VersionSpec(2, 25, 44, 34, 10, intArrayOf(6, 18)),
        VersionSpec(3, 29, 70, 55, 15, intArrayOf(6, 22)),
        VersionSpec(4, 33, 100, 80, 20, intArrayOf(6, 26)),
        VersionSpec(5, 37, 134, 108, 26, intArrayOf(6, 30)),
        VersionSpec(6, 41, 172, 136, 36, intArrayOf(6, 34)),
        VersionSpec(7, 45, 196, 156, 40, intArrayOf(6, 22, 38))
    )

    fun generateQrBitmap(text: String, sizePx: Int = 512): Bitmap {
        val utf8Bytes = text.toByteArray(Charsets.UTF_8)
        val dataLen = utf8Bytes.size

        val spec = VERSION_SPECS.firstOrNull { it.dataCodewords >= dataLen + 3 } ?: VERSION_SPECS.last()
        val size = spec.size

        val bits = mutableListOf<Int>()
        fun pushBits(value: Int, length: Int) {
            for (i in length - 1 downTo 0) {
                bits.add((value shr i) and 1)
            }
        }

        pushBits(0b0100, 4)
        pushBits(dataLen, 8)
        for (b in utf8Bytes) {
            pushBits(b.toInt() and 0xFF, 8)
        }

        val totalDataBits = spec.dataCodewords * 8
        val termLen = minOf(4, totalDataBits - bits.size)
        pushBits(0, termLen)

        while (bits.size % 8 != 0) {
            bits.add(0)
        }

        val padBytes = intArrayOf(0xEC, 0x11)
        var padIdx = 0
        while (bits.size < totalDataBits) {
            pushBits(padBytes[padIdx % 2], 8)
            padIdx++
        }

        val dataBytes = IntArray(bits.size / 8)
        for (i in dataBytes.indices) {
            var b = 0
            for (j in 0 until 8) {
                b = (b shl 1) or bits[i * 8 + j]
            }
            dataBytes[i] = b
        }

        val ecBytes = rsEncode(dataBytes, spec.ecCodewords)
        val finalCodewords = IntArray(dataBytes.size + ecBytes.size)
        System.arraycopy(dataBytes, 0, finalCodewords, 0, dataBytes.size)
        System.arraycopy(ecBytes, 0, finalCodewords, dataBytes.size, ecBytes.size)

        val matrix = Array(size) { BooleanArray(size) }
        val isFunc = Array(size) { BooleanArray(size) }

        fun setFunc(r: Int, c: Int, v: Boolean) {
            if (r in 0 until size && c in 0 until size) {
                matrix[r][c] = v
                isFunc[r][c] = true
            }
        }

        fun drawFinder(r0: Int, c0: Int) {
            for (r in -1..7) {
                for (c in -1..7) {
                    if (r0 + r in 0 until size && c0 + c in 0 until size) {
                        val isBlack = (r in 0..6 && (c == 0 || c == 6)) ||
                                (c in 0..6 && (r == 0 || r == 6)) ||
                                (r in 2..4 && c in 2..4)
                        setFunc(r0 + r, c0 + c, isBlack)
                    }
                }
            }
        }

        drawFinder(0, 0)
        drawFinder(0, size - 7)
        drawFinder(size - 7, 0)

        for (i in 8 until size - 8) {
            setFunc(6, i, i % 2 == 0)
            setFunc(i, 6, i % 2 == 0)
        }

        if (spec.alignment.isNotEmpty()) {
            for (ar in spec.alignment) {
                for (ac in spec.alignment) {
                    if ((ar <= 8 && ac <= 8) || (ar <= 8 && ac >= size - 8) || (ar >= size - 8 && ac <= 8)) {
                        continue
                    }
                    for (r in -2..2) {
                        for (c in -2..2) {
                            setFunc(ar + r, ac + c, max(abs(r), abs(c)) != 1)
                        }
                    }
                }
            }
        }

        setFunc(size - 8, 8, true)
        for (i in 0..8) {
            if (i in 0 until size) {
                if (!isFunc[8][i]) setFunc(8, i, false)
                if (!isFunc[i][8]) setFunc(i, 8, false)
            }
        }
        for (i in 0..7) {
            if (size - 1 - i in 0 until size) {
                if (!isFunc[8][size - 1 - i]) setFunc(8, size - 1 - i, false)
                if (!isFunc[size - 1 - i][8]) setFunc(size - 1 - i, 8, false)
            }
        }

        var byteIdx = 0
        var bitIdx = 7
        var up = true

        var right = size - 1
        while (right > 0) {
            if (right == 6) right--
            for (vert in 0 until size) {
                val r = if (up) size - 1 - vert else vert
                for (c in intArrayOf(right, right - 1)) {
                    if (!isFunc[r][c]) {
                        var bit = false
                        if (byteIdx < finalCodewords.size) {
                            bit = ((finalCodewords[byteIdx] shr bitIdx) and 1) == 1
                            bitIdx--
                            if (bitIdx < 0) {
                                bitIdx = 7
                                byteIdx++
                            }
                        }
                        matrix[r][c] = bit
                    }
                }
            }
            up = !up
            right -= 2
        }

        val finalResult = Array(size) { BooleanArray(size) }
        for (r in 0 until size) {
            for (c in 0 until size) {
                if (isFunc[r][c]) {
                    finalResult[r][c] = matrix[r][c]
                } else {
                    finalResult[r][c] = matrix[r][c] xor (((r + c) % 2) == 0)
                }
            }
        }

        val formatBits = 0x77C4
        fun getFBit(i: Int): Boolean = ((formatBits shr i) and 1) == 1

        for (i in 0..5) finalResult[8][i] = getFBit(i)
        finalResult[8][7] = getFBit(6)
        finalResult[8][8] = getFBit(7)
        finalResult[7][8] = getFBit(8)
        for (i in 9..14) finalResult[14 - i][8] = getFBit(i)

        for (i in 0..7) finalResult[size - 1 - i][8] = getFBit(i)
        for (i in 8..14) finalResult[8][size - 15 + i] = getFBit(i)
        finalResult[size - 8][8] = true

        val border = 4
        val fullDim = size + border * 2
        val bitmap = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.WHITE)

        val scale = sizePx.toFloat() / fullDim.toFloat()
        val canvas = android.graphics.Canvas(bitmap)
        val paint = android.graphics.Paint().apply {
            color = Color.BLACK
            style = android.graphics.Paint.Style.FILL
        }

        for (r in 0 until size) {
            for (c in 0 until size) {
                if (finalResult[r][c]) {
                    val left = (c + border) * scale
                    val top = (r + border) * scale
                    canvas.drawRect(left, top, left + scale + 0.5f, top + scale + 0.5f, paint)
                }
            }
        }

        return bitmap
    }
}