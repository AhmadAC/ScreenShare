import React, {useEffect, useRef} from 'react';

// Galois Field (256) tables
const GF_EXP = new Uint8Array(512);
const GF_LOG = new Uint8Array(256);

(function initGF() {
    let x = 1;
    for (let i = 0; i < 255; i++) {
        GF_EXP[i] = x;
        GF_EXP[i + 255] = x;
        GF_LOG[x] = i;
        x <<= 1;
        if (x & 256) x ^= 0x11d;
    }
})();

function gfMul(x: number, y: number): number {
    if (x === 0 || y === 0) return 0;
    return GF_EXP[GF_LOG[x] + GF_LOG[y]];
}

function rsGeneratorPoly(degree: number): Uint8Array {
    let poly = new Uint8Array([1]);
    for (let i = 0; i < degree; i++) {
        const next = new Uint8Array(poly.length + 1);
        const root = GF_EXP[i];
        for (let j = 0; j < poly.length; j++) {
            next[j] ^= gfMul(poly[j], root);
            next[j + 1] ^= poly[j];
        }
        poly = next;
    }
    return poly;
}

function rsEncode(data: number[], numEcBytes: number): number[] {
    const gen = rsGeneratorPoly(numEcBytes);
    const msg = new Uint8Array(data.length + numEcBytes);
    msg.set(data);
    for (let i = 0; i < data.length; i++) {
        const coef = msg[i];
        if (coef !== 0) {
            for (let j = 0; j < gen.length; j++) {
                msg[i + j] ^= gfMul(gen[j], coef);
            }
        }
    }
    return Array.from(msg.slice(data.length));
}

// Version table specifications for Error Correction Level L
const VERSION_SPECS = [
    {version: 1, size: 21, totalCodewords: 26, dataCodewords: 19, ecCodewords: 7, alignment: [] as number[]},
    {version: 2, size: 25, totalCodewords: 44, dataCodewords: 34, ecCodewords: 10, alignment: [6, 18]},
    {version: 3, size: 29, totalCodewords: 70, dataCodewords: 55, ecCodewords: 15, alignment: [6, 22]},
    {version: 4, size: 33, totalCodewords: 100, dataCodewords: 80, ecCodewords: 20, alignment: [6, 26]},
    {version: 5, size: 37, totalCodewords: 134, dataCodewords: 108, ecCodewords: 26, alignment: [6, 30]},
    {version: 6, size: 41, totalCodewords: 172, dataCodewords: 136, ecCodewords: 36, alignment: [6, 34]},
    {version: 7, size: 45, totalCodewords: 196, dataCodewords: 156, ecCodewords: 40, alignment: [6, 22, 38]},
];

const FORMAT_INFO_L = [0x77c4, 0x72f3, 0x7daa, 0x789d, 0x662f, 0x6318, 0x6c41, 0x6976];

export function generateQRMatrix(text: string): boolean[][] {
    const utf8Bytes = new TextEncoder().encode(text);
    const dataLen = utf8Bytes.length;

    const spec = VERSION_SPECS.find((s) => s.dataCodewords >= dataLen + 3) || VERSION_SPECS[VERSION_SPECS.length - 1];
    const size = spec.size;

    // Build data bitstream (Byte Mode: 0b0100)
    const bits: number[] = [];
    const pushBits = (val: number, len: number) => {
        for (let i = len - 1; i >= 0; i--) {
            bits.push((val >> i) & 1);
        }
    };

    pushBits(0b0100, 4);
    pushBits(dataLen, 8);
    for (let i = 0; i < dataLen; i++) {
        pushBits(utf8Bytes[i], 8);
    }

    // Terminator
    const totalDataBits = spec.dataCodewords * 8;
    const termLen = Math.min(4, totalDataBits - bits.length);
    pushBits(0, termLen);

    // Byte alignment padding
    while (bits.length % 8 !== 0) {
        bits.push(0);
    }

    // Pad bytes 0xEC and 0x11
    const padBytes = [0xec, 0x11];
    let padIdx = 0;
    while (bits.length < totalDataBits) {
        pushBits(padBytes[padIdx % 2], 8);
        padIdx++;
    }

    const dataBytes: number[] = [];
    for (let i = 0; i < bits.length; i += 8) {
        let b = 0;
        for (let j = 0; j < 8; j++) {
            b = (b << 1) | bits[i + j];
        }
        dataBytes.push(b);
    }

    const ecBytes = rsEncode(dataBytes, spec.ecCodewords);
    const finalCodewords = dataBytes.concat(ecBytes);

    // Matrix construction
    const matrix: (boolean | null)[][] = Array.from({length: size}, () => Array(size).fill(null));
    const isFunction: boolean[][] = Array.from({length: size}, () => Array(size).fill(false));

    const setFunc = (r: number, c: number, val: boolean) => {
        if (r >= 0 && r < size && c >= 0 && c < size) {
            matrix[r][c] = val;
            isFunction[r][c] = true;
        }
    };

    // Finder patterns
    const drawFinder = (r0: number, c0: number) => {
        for (let r = -1; r <= 7; r++) {
            for (let c = -1; c <= 7; c++) {
                const isBlack = (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
                                (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
                                (r >= 2 && r <= 4 && c >= 2 && c <= 4);
                setFunc(r0 + r, c0 + c, isBlack);
            }
        }
    };

    drawFinder(0, 0);
    drawFinder(0, size - 7);
    drawFinder(size - 7, 0);

    // Timing patterns
    for (let i = 8; i < size - 8; i++) {
        setFunc(6, i, i % 2 === 0);
        setFunc(i, 6, i % 2 === 0);
    }

    // Alignment patterns
    if (spec.alignment.length > 0) {
        for (const ar of spec.alignment) {
            for (const ac of spec.alignment) {
                if ((ar <= 8 && ac <= 8) || (ar <= 8 && ac >= size - 8) || (ar >= size - 8 && ac <= 8)) continue;
                for (let r = -2; r <= 2; r++) {
                    for (let c = -2; c <= 2; c++) {
                        const isBlack = Math.max(Math.abs(r), Math.abs(c)) !== 1;
                        setFunc(ar + r, ac + c, isBlack);
                    }
                }
            }
        }
    }

    // Dark module & format reservations
    setFunc(size - 8, 8, true);
    for (let i = 0; i < 9; i++) {
        if (!isFunction[8][i]) setFunc(8, i, false);
        if (!isFunction[i][8]) setFunc(i, 8, false);
    }
    for (let i = 0; i < 8; i++) {
        if (!isFunction[8][size - 1 - i]) setFunc(8, size - 1 - i, false);
        if (!isFunction[size - 1 - i][8]) setFunc(size - 1 - i, 8, false);
    }

    // Place codewords into data areas
    let byteIdx = 0;
    let bitIdx = 7;
    let up = true;

    for (let right = size - 1; right > 0; right -= 2) {
        if (right === 6) right--; // Skip vertical timing column
        for (let vert = 0; vert < size; vert++) {
            const r = up ? size - 1 - vert : vert;
            for (let c = right; c >= right - 1; c--) {
                if (!isFunction[r][c]) {
                    let bit = false;
                    if (byteIdx < finalCodewords.length) {
                        bit = ((finalCodewords[byteIdx] >> bitIdx) & 1) === 1;
                        bitIdx--;
                        if (bitIdx < 0) {
                            bitIdx = 7;
                            byteIdx++;
                        }
                    }
                    matrix[r][c] = bit;
                }
            }
        }
        up = !up;
    }

    // Apply optimal mask pattern
    const maskFn = (r: number, c: number) => (r + c) % 2 === 0;
    const finalResult: boolean[][] = Array.from({length: size}, () => Array(size).fill(false));

    for (let r = 0; r < size; r++) {
        for (let c = 0; c < size; c++) {
            if (isFunction[r][c]) {
                finalResult[r][c] = matrix[r][c] ?? false;
            } else {
                finalResult[r][c] = (matrix[r][c] ?? false) !== maskFn(r, c);
            }
        }
    }

    // Write format info (Mask 0: 0x77c4)
    const formatBits = FORMAT_INFO_L[0];
    const getFormatBit = (i: number) => ((formatBits >> (14 - i)) & 1) === 1;

    // Top-left
    finalResult[8][0] = getFormatBit(0);
    finalResult[8][1] = getFormatBit(1);
    finalResult[8][2] = getFormatBit(2);
    finalResult[8][3] = getFormatBit(3);
    finalResult[8][4] = getFormatBit(4);
    finalResult[8][5] = getFormatBit(5);
    finalResult[8][7] = getFormatBit(6);
    finalResult[8][8] = getFormatBit(7);
    finalResult[7][8] = getFormatBit(8);
    finalResult[5][8] = getFormatBit(9);
    finalResult[4][8] = getFormatBit(10);
    finalResult[3][8] = getFormatBit(11);
    finalResult[2][8] = getFormatBit(12);
    finalResult[1][8] = getFormatBit(13);
    finalResult[0][8] = getFormatBit(14);

    // Split across edges
    for (let i = 0; i < 7; i++) {
        finalResult[size - 1 - i][8] = getFormatBit(i);
    }
    for (let i = 0; i < 8; i++) {
        finalResult[8][size - 8 + i] = getFormatBit(7 + i);
    }

    return finalResult;
}

export const QRCodeCanvas: React.FC<{text: string; size?: number}> = ({text, size = 110}) => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        try {
            const matrix = generateQRMatrix(text);
            const matrixSize = matrix.length;
            const quietZone = 2;
            const totalModules = matrixSize + quietZone * 2;
            const moduleSize = Math.floor(size / totalModules);
            const actualSize = moduleSize * totalModules;

            canvas.width = actualSize;
            canvas.height = actualSize;

            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, actualSize, actualSize);

            ctx.fillStyle = '#1d2021';
            for (let r = 0; r < matrixSize; r++) {
                for (let c = 0; c < matrixSize; c++) {
                    if (matrix[r][c]) {
                        ctx.fillRect((c + quietZone) * moduleSize, (r + quietZone) * moduleSize, moduleSize, moduleSize);
                    }
                }
            }
        } catch (e) {
            console.error('Failed to render QR Code:', e);
        }
    }, [text, size]);

    return <canvas ref={canvasRef} style={{display: 'block', borderRadius: '4px'}} />;
};