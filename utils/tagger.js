// tagger.js - VERSION 3.0 - DATA-DRIVEN DETERMINISM
// NEW IN V3.0:
// - Extracts "Ground Truth" profiles for each element
// - Returns: {selector, text, tag, attributes} instead of just selector
// - Eliminates visual guessing by providing exact DOM data
// PRESERVED FROM V2.0:
// - Shadow DOM Support
// - DOM Stabilization
// - Dropdown Option Support

(function() {
    // ============================================
    // PHASE 2: DOM STABILIZATION
    // Wait for the page to stop changing before tagging
    // ============================================
    return new Promise((resolve) => {
        let stabilityTimer;
        
        // Failsafe: If page never settles after 3 seconds, tag anyway
        const maxWaitTimer = setTimeout(() => {
            if (observer) observer.disconnect();
            console.log('[Tagger v3.0] Failsafe triggered: Page still changing after 3s, tagging anyway');
            resolve(performTagging());
        }, 3000);

        // MutationObserver to detect DOM changes
        const observer = new MutationObserver(() => {
            clearTimeout(stabilityTimer);
            
            // Start a new stability countdown
            stabilityTimer = setTimeout(() => {
                // DOM has been stable for 300ms!
                clearTimeout(maxWaitTimer); // Cancel failsafe
                observer.disconnect();
                console.log('[Tagger v3.0] DOM stable for 300ms, starting tagging');
                resolve(performTagging());
            }, 300);
        });
        
        // Watch for changes in the entire document
        observer.observe(document.body, {
            subtree: true,
            childList: true,
            attributes: false // Don't care about attribute changes (reduces noise)
        });
        
        // Kickstart the stability timer immediately
        stabilityTimer = setTimeout(() => {
            clearTimeout(maxWaitTimer);
            observer.disconnect();
            console.log('[Tagger v3.0] Page was already stable, starting tagging');
            resolve(performTagging());
        }, 300);
    });

    // ============================================
    // MAIN TAGGING FUNCTION
    // ============================================
    function performTagging() {
        // Remove any existing tags from previous runs
        const existingTags = document.querySelectorAll('.robo-tester-tag');
        existingTags.forEach(tag => tag.remove());

        // ============================================
        // PHASE 1: SHADOW DOM SUPPORT
        // Recursive function to find ALL elements, including inside shadow roots
        // ============================================
        function getAllElementsIncludingShadow(root) {
            const selectors = [
                'button',
                'a[href]',
                'input',
                'textarea',
                'select',
                '[role="button"]',
                '[role="link"]',
                '[onclick]',
                '[type="submit"]',
                '.cursor-pointer',
                '[style*="cursor: pointer"]',
                '[style*="cursor:pointer"]',
                'div[onclick]',
            ];
            
            // Get elements from current root
            let elements = Array.from(root.querySelectorAll(selectors.join(', ')));
            
            // Now recursively search shadow roots
            const allNodes = root.querySelectorAll('*');
            allNodes.forEach(node => {
                if (node.shadowRoot) {
                    console.log('[Tagger v3.0] Found shadow root in:', node.tagName);
                    // Recursively get elements from this shadow root
                    const shadowElements = getAllElementsIncludingShadow(node.shadowRoot);
                    elements = elements.concat(shadowElements);
                }
            });
            
            return elements;
        }

        // ============================================
        // NEW IN V3.0: EXTRACT ELEMENT PROFILE
        // Returns complete "Ground Truth" data about an element
        // ============================================
        function extractElementProfile(el) {
            const profile = {
                selector: null,  // Will be filled by getUniversalSelector()
                text: '',
                tag: el.tagName.toLowerCase(),
                attributes: {}
            };
            
            // Extract text content (normalize whitespace)
            let textContent = '';
            
            // For input elements, get placeholder or value
            if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea') {
                textContent = el.placeholder || el.value || '';
            } else {
                // Get direct text content (not from children)
                for (let node of el.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        textContent += node.textContent;
                    }
                }
            }
            
            // Normalize whitespace: trim and replace multiple spaces with single space
            profile.text = textContent.trim().replace(/\s+/g, ' ');
            
            // Extract key attributes
            const keyAttributes = [
                'id', 'name', 'type', 'class', 'value',
                'aria-label', 'aria-labelledby', 'placeholder',
                'role', 'href', 'title', 'alt'
            ];
            
            keyAttributes.forEach(attr => {
                const value = el.getAttribute(attr);
                if (value !== null && value !== '') {
                    profile.attributes[attr] = value;
                }
            });
            
            // Also capture data-* attributes
            Array.from(el.attributes).forEach(attr => {
                if (attr.name.startsWith('data-')) {
                    profile.attributes[attr.name] = attr.value;
                }
            });
            
            return profile;
        }

        // Get ALL interactive elements (including shadow DOM)
        const elements = getAllElementsIncludingShadow(document);
        console.log(`[Tagger v3.0] Found ${elements.length} total interactive elements (including shadow DOM)`);

        const elementMap = {};
        let idCounter = 1;

        // ============================================
        // HELPER FUNCTIONS
        // ============================================
        
        // Get text content (excluding children)
        function getDirectText(el) {
            let text = '';
            for (let node of el.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) {
                    text += node.textContent.trim();
                }
            }
            return text;
        }

        // Check if selector is unique
        function isUnique(selector) {
            try {
                return document.querySelectorAll(selector).length === 1;
            } catch (e) {
                return false;
            }
        }

        // Get nth-child index
        function getNthChildIndex(el) {
            let index = 1;
            let sibling = el.previousElementSibling;
            while (sibling) {
                index++;
                sibling = sibling.previousElementSibling;
            }
            return index;
        }

        // Build a CSS path using nth-child
        function buildCSSPath(el, maxDepth = 5) {
            const path = [];
            let current = el;
            let depth = 0;

            while (current && current.nodeType === Node.ELEMENT_NODE && depth < maxDepth) {
                let selector = current.tagName.toLowerCase();
                
                // Add nth-child for specificity
                const nthIndex = getNthChildIndex(current);
                selector += `:nth-child(${nthIndex})`;
                
                path.unshift(selector);
                
                current = current.parentElement;
                depth++;
                
                // Stop at body or if we have a unique selector
                if (current === document.body || isUnique(path.join(' > '))) {
                    break;
                }
            }
            
            return path.join(' > ');
        }

        // ============================================
        // SELECTOR GENERATION (Universal Strategy)
        // ============================================
        function getUniversalSelector(el) {
            // STRATEGY 1: ID (most reliable)
            if (el.id && /^[a-zA-Z][\w-]*$/.test(el.id)) {
                const selector = `#${el.id}`;
                if (isUnique(selector)) return selector;
            }

            // STRATEGY 2: Unique name attribute
            if (el.name) {
                const selector = `[name="${el.name}"]`;
                if (isUnique(selector)) return selector;
            }

            // STRATEGY 3: Unique data attribute
            for (let attr of el.attributes) {
                if (attr.name.startsWith('data-') && attr.value) {
                    const selector = `[${attr.name}="${attr.value}"]`;
                    if (isUnique(selector)) return selector;
                }
            }

            // STRATEGY 4: Text content (for buttons/links)
            const text = getDirectText(el);
            if (text && text.length > 0 && text.length < 100) {
                const tagName = el.tagName.toLowerCase();
                if (tagName === 'button' || tagName === 'a') {
                    // Use text-based selector (Playwright supports this)
                    return `${tagName}:has-text("${text.replace(/"/g, '\\"')}")`;
                }
            }

            // STRATEGY 5: Type attribute (unique)
            if (el.type && el.tagName.toLowerCase() !== 'div') {
                const selector = `${el.tagName.toLowerCase()}[type="${el.type}"]`;
                if (isUnique(selector)) return selector;
            }

            // STRATEGY 6: Unique combination of tag + aria attributes
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) {
                const selector = `${el.tagName.toLowerCase()}[aria-label="${ariaLabel}"]`;
                if (isUnique(selector)) return selector;
            }

            const ariaLabelledby = el.getAttribute('aria-labelledby');
            if (ariaLabelledby) {
                const selector = `${el.tagName.toLowerCase()}[aria-labelledby="${ariaLabelledby}"]`;
                if (isUnique(selector)) return selector;
            }

            // STRATEGY 7: CSS path with nth-child (UNIVERSAL FALLBACK)
            return buildCSSPath(el);
        }

        // ============================================
        // STEP 1: Tag all regular interactive elements
        // ============================================
        elements.forEach(element => {
            // Check if element is visible
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            
            const isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0'
            );

            if (!isVisible) return;

            // NEW V3.0: Extract complete profile
            const profile = extractElementProfile(element);
            
            // Generate selector
            profile.selector = getUniversalSelector(element);
            
            const elementId = idCounter++;

            // Store profile (not just selector!)
            elementMap[elementId] = profile;

            // Create visual tag
            const tag = document.createElement('div');
            tag.className = 'robo-tester-tag';
            tag.style.cssText = `
                position: absolute;
                border: 2px solid red;
                pointer-events: none;
                z-index: 999999;
                box-sizing: border-box;
            `;

            // Position the red box over the element
            const scrollX = window.scrollX || window.pageXOffset;
            const scrollY = window.scrollY || window.pageYOffset;
            
            tag.style.left = (rect.left + scrollX) + 'px';
            tag.style.top = (rect.top + scrollY) + 'px';
            tag.style.width = rect.width + 'px';
            tag.style.height = rect.height + 'px';

            // Create number badge
            const badge = document.createElement('div');
            badge.style.cssText = `
                position: absolute;
                top: -8px;
                left: -8px;
                background: red;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: Arial, sans-serif;
            `;
            badge.textContent = elementId;

            tag.appendChild(badge);
            document.body.appendChild(tag);
        });

        // ============================================
        // STEP 2: Handle <select> dropdown options
        // NEW V3.0: Extract option text AND value
        // ============================================
        
        const selectElements = document.querySelectorAll('select');
        
        selectElements.forEach(selectElement => {
            // Check if this select is visible
            const selectRect = selectElement.getBoundingClientRect();
            const selectStyle = window.getComputedStyle(selectElement);
            
            const isSelectVisible = (
                selectRect.width > 0 &&
                selectRect.height > 0 &&
                selectStyle.display !== 'none' &&
                selectStyle.visibility !== 'hidden'
            );

            if (!isSelectVisible) return;

            // Find the select element's ID in elementMap
            let selectId = null;
            const selectSelector = getUniversalSelector(selectElement);
            
            for (let id in elementMap) {
                if (elementMap[id].selector === selectSelector) {
                    selectId = id;
                    break;
                }
            }

            if (!selectId) return; // Skip if select wasn't tagged

            // Now tag each <option> inside this <select>
            const options = selectElement.querySelectorAll('option');
            let validOptionIndex = 0; // Counter for valid options only
            
            options.forEach((option) => {
                // Skip empty, disabled, or placeholder options
                if (!option.value || 
                    option.disabled || 
                    option.value === '' || 
                    option.value === 'select' ||
                    option.hasAttribute('disabled')) {
                    return;
                }
                
                // Create a unique ID for this option (e.g., "10a", "10b", "10c")
                const optionLetter = String.fromCharCode(97 + validOptionIndex); // 97 = 'a'
                const optionId = `${selectId}${optionLetter}`;
                
                // Create selector for this specific option
                const optionSelector = `${selectSelector} option[value="${option.value}"]`;
                
                // NEW V3.0: Extract option profile with text AND value
                const optionProfile = {
                    selector: optionSelector,
                    text: option.textContent.trim().replace(/\s+/g, ' '), // Normalized text
                    tag: 'option',
                    attributes: {
                        value: option.value,
                        'parent-select': selectSelector
                    }
                };
                
                // Store profile in element map
                elementMap[optionId] = optionProfile;
                
                // Create visual indicator (blue badge next to the select)
                const optionBadge = document.createElement('div');
                optionBadge.className = 'robo-tester-tag';
                optionBadge.style.cssText = `
                    position: absolute;
                    background: blue;
                    color: white;
                    font-weight: bold;
                    font-size: 10px;
                    padding: 2px 5px;
                    border-radius: 3px;
                    font-family: Arial, sans-serif;
                    z-index: 999999;
                    pointer-events: none;
                    white-space: nowrap;
                `;
                
                // Position it next to the select element
                const scrollX = window.scrollX || window.pageXOffset;
                const scrollY = window.scrollY || window.pageYOffset;
                
                // Stack option badges vertically next to the select
                optionBadge.style.left = (selectRect.right + scrollX + 5) + 'px';
                optionBadge.style.top = (selectRect.top + scrollY + (validOptionIndex * 20)) + 'px';
                
                // Show option ID and text
                const displayText = optionProfile.text.length > 20 ? 
                    optionProfile.text.substring(0, 20) + '...' : 
                    optionProfile.text;
                optionBadge.textContent = `${optionId}: ${displayText}`;
                
                document.body.appendChild(optionBadge);
                
                validOptionIndex++;
            });
        });

        console.log(`[Tagger v3.0] Tagged ${Object.keys(elementMap).length} total elements with Ground Truth profiles`);
        
        // Return the mapping as a JSON string
        return JSON.stringify(elementMap);
    }
})();