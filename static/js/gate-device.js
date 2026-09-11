(() => {
  // Kasama ang touch-based iPad detection dahil minsan desktop ang user-agent nito.
  window.sibolMobileScanner = Boolean(
    navigator.userAgentData?.mobile ||
    /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ||
    (/Macintosh/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1)
  );
})();
