(() => {
  const gallery = document.querySelector('.home-gallery');
  if (!gallery || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const photos = [1, 2, 3, 4, 5, 6];
  const current = gallery.querySelector('.frame-current');
  const next = gallery.querySelector('.frame-next');
  let index = 0;
  const image = number => `url('/static/images/pic${number}.jpg')`;
  current.style.backgroundImage = image(photos[index]);
  next.style.backgroundImage = image(photos[(index + 1) % photos.length]);
  setInterval(() => {
    next.classList.add('is-visible');
    setTimeout(() => {
      index = (index + 1) % photos.length;
      current.style.backgroundImage = image(photos[index]);
      next.classList.remove('is-visible');
      next.style.backgroundImage = image(photos[(index + 1) % photos.length]);
    }, 1400);
  }, 7500);
})();
