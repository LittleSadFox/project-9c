export const HALPE26_NAMES = [
  "nose",
  "left_eye",
  "right_eye",
  "left_ear",
  "right_ear",
  "left_shoulder",
  "right_shoulder",
  "left_elbow",
  "right_elbow",
  "left_wrist",
  "right_wrist",
  "left_hip",
  "right_hip",
  "left_knee",
  "right_knee",
  "left_ankle",
  "right_ankle",
  "head",
  "neck",
  "hip",
  "left_big_toe",
  "right_big_toe",
  "left_small_toe",
  "right_small_toe",
  "left_heel",
  "right_heel",
];

export const HALPE26_EDGES = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 4],
  [0, 17],
  [17, 18],
  [18, 5],
  [18, 6],
  [5, 7],
  [7, 9],
  [6, 8],
  [8, 10],
  [18, 19],
  [19, 11],
  [19, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [15, 20],
  [15, 22],
  [15, 24],
  [16, 21],
  [16, 23],
  [16, 25],
];

const LEFT = new Set([1, 3, 5, 7, 9, 11, 13, 15, 20, 22, 24]);
const RIGHT = new Set([2, 4, 6, 8, 10, 12, 14, 16, 21, 23, 25]);

export function keypointSide(index) {
  if (LEFT.has(index)) {
    return "left";
  }
  if (RIGHT.has(index)) {
    return "right";
  }
  return "center";
}

export function edgeSide(a, b) {
  const left = keypointSide(a);
  const right = keypointSide(b);
  if (left === right) {
    return left;
  }
  return "center";
}
