/**
 * modal-helper.js — 負責全域 Modal 開關與背景捲動防護（ESM Component）
 */

/**
 * 監聽全域 Modal (modal-backdrop) 的開關狀態，防範背景 Scroll Bleed
 * 當任一 Modal 開啟時，於 document.body 加上 'modal-open' class
 * 
 * @returns {void}
 */
export function initModalObserver() {
    if (typeof window === 'undefined') return;

    const modalBackdrops = document.querySelectorAll('.modal-backdrop');
    let shadowModalOpenCount = 0;

    const updateBodyScroll = () => {
        let hasVisibleModal = shadowModalOpenCount > 0;
        modalBackdrops.forEach(el => {
            if (el.style.display !== 'none' && el.style.visibility !== 'hidden') {
                hasVisibleModal = true;
            }
        });
        if (hasVisibleModal) {
            document.body.classList.add('modal-open');
        } else {
            document.body.classList.remove('modal-open');
        }
    };

    const observer = new MutationObserver((mutations) => {
        mutations.forEach(mutation => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                updateBodyScroll();
            }
        });
    });

    modalBackdrops.forEach(el => {
        observer.observe(el, { attributes: true, attributeFilter: ['style'] });
    });

    document.addEventListener('modal-opened', () => {
        shadowModalOpenCount++;
        updateBodyScroll();
    });

    document.addEventListener('modal-closed', () => {
        shadowModalOpenCount = Math.max(0, shadowModalOpenCount - 1);
        updateBodyScroll();
    });

    // 初始檢查一次
    updateBodyScroll();
}
