Object.defineProperty(window, "analysis", {
  configurable: true,
  get(){ return analysis; },
  set(value){ analysis = value; }
});
