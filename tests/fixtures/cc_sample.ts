function base() {
  return 1;
}

function withIf() {
  if (true) {
    return 2;
  }
}

function withSwitch(x: number) {
  switch (x) {
    case 1:
      return 1;
    case 2:
      return 2;
    default:
      return 0;
  }
}
