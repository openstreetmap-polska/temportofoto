const gugikWmsUrl = 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/SkorowidzeWgAktualnosci';
const zoomLowLevelMaxValue = 11;

function getSelectedSheetLayers() {
    const selectedCheckboxes = document.querySelectorAll('.layer-checkbox[data-category="sheets"]:checked');
    return Array.from(selectedCheckboxes).map(cb => cb.value);
}

function buildGetFeatureInfoUrl(wmsUrl, layers, x, y) {
    const bounds = map.getBounds();
    const size = map.getSize();
    
    // Convert lat/lng click to pixel coordinates
    const point = map.latLngToContainerPoint([y, x]);
    
    const params = new URLSearchParams({
        service: 'WMS',
        version: '1.3.0',
        request: 'GetFeatureInfo',
        layers: layers.join(','),
        query_layers: layers.join(','),
        info_format: 'text/html',
        width: Math.round(size.x),
        height: Math.round(size.y),
        crs: 'EPSG:4326',
        bbox: `${bounds.getSouth()},${bounds.getWest()},${bounds.getNorth()},${bounds.getEast()}`,
        x: Math.round(point.x),
        y: Math.round(point.y)
    });
    
    return `${wmsUrl}?${params.toString()}`;
}

function parseGetFeatureInfoResponse(html) {
    const features = [];
    
    // Extract JavaScript arrays from HTML using regex
    const arrayRegex = /skorDo5cm\.push\(\{([^}]+)\}\);/g;
    let match;
    
    while ((match = arrayRegex.exec(html)) !== null) {
        const objStr = '{' + match[1] + '}';
        try {
            // Parse the object properties
            const props = {};
            const propRegex = /(\w+):"([^"]*)"(?:,|$)/g;
            let propMatch;
            
            while ((propMatch = propRegex.exec(match[1])) !== null) {
                props[propMatch[1]] = propMatch[2];
            }
            
            // Filter for RGB only
            if (props.kolor === 'RGB') {
                features.push({
                    url: props.url,
                    aktualnosc: props.aktualnosc,
                    wielkoscPiksela: props.wielkoscPiksela,
                    kolor: props.kolor,
                    aktualnoscRok: props.aktualnoscRok,
                    dt_pzgik: props.dt_pzgik,
                    godlo: props.godlo
                });
            }
        } catch (e) {
            console.error('Error parsing feature:', e);
        }
    }
    
    return features;
}

function formatFeaturesForPopup(features) {
    if (features.length === 0) {
        return 'Nie znaleziono dostępnych arkuszy';
    }
    
    // Sort by aktualnoscRok descending, then by wielkoscPiksela ascending
    const sortedFeatures = [...features].sort((a, b) => {
        const yearA = parseInt(a.aktualnoscRok) || 0;
        const yearB = parseInt(b.aktualnoscRok) || 0;
        
        if (yearA !== yearB) {
            return yearB - yearA; // Descending
        }
        
        const pixelA = parseFloat(a.wielkoscPiksela) || 0;
        const pixelB = parseFloat(b.wielkoscPiksela) || 0;
        
        return pixelA - pixelB; // Ascending
    });
    
    let html = '<div class="popup-features-container">';
    sortedFeatures.forEach(feature => {
        html += `<div class="popup-feature-item">`;
        html += `<strong>${feature.godlo}</strong> (${feature.aktualnoscRok})<br/>`;
        html += `Aktualność: ${feature.aktualnosc}<br/>`;
        html += `Piksel: ${feature.wielkoscPiksela}<br/>`;
        html += `Data: ${feature.dt_pzgik}<br/>`;
        html += `<a href="${feature.url}" target="_blank" class="popup-download-link">Link do pobrania pliku</a>`;
        html += `</div>`;
    });
    html += '</div>';
    
    return html;
}

function onMapClick(e) {
    const currentZoom = map.getZoom();
    
    if (currentZoom <= ZOOM_LEVEL_MAX_VALUE) {
        L.popup()
            .setLatLng(e.latlng)
            .setContent('Przybliż mapę i włącz warstwy arkuszy')
            .openOn(map);
    } else {
        const selectedLayers = getSelectedSheetLayers();
        
        if (selectedLayers.length === 0) {
            L.popup()
                .setLatLng(e.latlng)
                .setContent('Włącz przynajmniej jedną warstwę arkuszy')
                .openOn(map);
        } else {
            // Make GetFeatureInfo request
            const url = buildGetFeatureInfoUrl(gugikWmsUrl, selectedLayers, e.latlng.lng, e.latlng.lat);
            
            fetch(url)
                .then(response => response.text())
                .then(html => {
                    const features = parseGetFeatureInfoResponse(html);
                    const popupContent = formatFeaturesForPopup(features);
                    
                    L.popup()
                        .setLatLng(e.latlng)
                        .setContent(popupContent)
                        .openOn(map);
                })
                .catch(error => {
                    console.error('Error fetching GetFeatureInfo:', error);
                    L.popup()
                        .setLatLng(e.latlng)
                        .setContent('Błąd przy pobieraniu danych')
                        .openOn(map);
                });
        }
    }
}

function getWmsLayers(url) {
    return fetch(`${url}?service=WMS&request=GetCapabilities`)
        .then(response => response.text())
        .then(xmlText => {
            const parser = new DOMParser();
            const xmlDoc = parser.parseFromString(xmlText, 'text/xml');
            
            // Get all Layer elements that are children of the parent Layer
            const layers = xmlDoc.querySelectorAll('Layer > Layer');
            const layerNames = [];
            
            layers.forEach(layer => {
                const nameElement = layer.querySelector('Name');
                const titleElement = layer.querySelector('Title');
                const logoUrlElement = layer.querySelector('Attribution LogoURL OnlineResource');
                
                if (nameElement) {
                    const title = titleElement?.textContent || nameElement.textContent;
                    const category = title.includes('zasięg') ? 'extent' : 'sheets';
                    const imageUrl = logoUrlElement?.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || '';
                    
                    layerNames.push({
                        name: nameElement.textContent,
                        title: title,
                        category: category,
                        imageUrl: imageUrl
                    });
                }
            });
            
            return layerNames;
        });
}

function sortLayersForWms(layerNames) {
    // Sort layers: first "Starsze" layers, then by year ascending
    const sorted = [...layerNames].sort((a, b) => {
        const aHasStarsze = a.includes('Starsze');
        const bHasStarsze = b.includes('Starsze');
        
        // If one has "Starsze" and other doesn't, "Starsze" comes first
        if (aHasStarsze && !bHasStarsze) return -1;
        if (!aHasStarsze && bHasStarsze) return 1;
        
        // Extract 4-digit year from names
        const aYear = a.match(/\d{4}/)?.[0] || '9999';
        const bYear = b.match(/\d{4}/)?.[0] || '9999';
        
        // Sort by year ascending
        return parseInt(aYear) - parseInt(bYear);
    });
    
    return sorted;
}

const WMS_LAYER_OPTIONS = {
    format: 'image/png',
    transparent: true,
    opacity: 0.7,
    tileSize: 512,
};

const ZOOM_LEVEL_MAX_VALUE = 11;

const map = L.map('map').setView([52.24, 19.74], 6);

const basemap = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

let gugikWmsLayer = null;

function updateWmsLayer() {
    const selectedCheckboxes = document.querySelectorAll('.layer-checkbox:checked');
    const selectedLayers = Array.from(selectedCheckboxes).map(cb => cb.value);
    
    // Sort selected layers according to rules
    const sortedLayers = sortLayersForWms(selectedLayers);
    const layersParam = sortedLayers.join(',');
    
    if (layersParam === '') {
        // Remove layer if no layers selected
        if (gugikWmsLayer) {
            map.removeLayer(gugikWmsLayer);
            gugikWmsLayer = null;
        }
    } else {
        // Add or update layer with selected layers
        if (gugikWmsLayer) {
            map.removeLayer(gugikWmsLayer);
        }
        gugikWmsLayer = L.tileLayer.wms(gugikWmsUrl, {
            ...WMS_LAYER_OPTIONS,
            layers: layersParam
        }).addTo(map);
    }
}

function updateVisibleLayers() {
    const currentZoom = map.getZoom();
    const extentSection = document.querySelector('[data-section="extent"]');
    const sheetsSection = document.querySelector('[data-section="sheets"]');
    
    if (currentZoom <= zoomLowLevelMaxValue) {
        // Extent visible, sheets disabled
        if (extentSection) {
            extentSection.classList.remove('section-disabled');
            extentSection.removeAttribute('title');
            extentSection.querySelectorAll('.layer-checkbox').forEach(cb => cb.disabled = false);
        }
        if (sheetsSection) {
            sheetsSection.classList.add('section-disabled');
            sheetsSection.title = 'Przybliż mapę by włączyć sekcję.';
            sheetsSection.querySelectorAll('.layer-checkbox').forEach(cb => cb.disabled = true);
        }
    } else {
        // Sheets visible, extent disabled
        if (extentSection) {
            extentSection.classList.add('section-disabled');
            extentSection.title = 'Oddal mapę by włączyć sekcję.';
            extentSection.querySelectorAll('.layer-checkbox').forEach(cb => cb.disabled = true);
        }
        if (sheetsSection) {
            sheetsSection.classList.remove('section-disabled');
            sheetsSection.removeAttribute('title');
            sheetsSection.querySelectorAll('.layer-checkbox').forEach(cb => cb.disabled = false);
        }
    }
}

map.on('click', onMapClick);

function loadAndRenderLayers(wmsUrl) {
    return getWmsLayers(wmsUrl)
        .then(layers => {
            const container = document.getElementById('layersContainer');
            
            // Remove loading message and old sections, but keep the h3
            document.getElementById('loadingMessage')?.remove();
            document.querySelectorAll('[data-section]').forEach(s => s.remove());
            
            if (layers.length === 0) {
                container.innerHTML += '<p>Nie znaleziono żadnych warstw</p>';
                return;
            }
            
            layers.forEach(layer => {
                const label = document.createElement('label');
                label.className = 'layer-label';
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.value = layer.name;
                checkbox.className = 'layer-checkbox';
                checkbox.dataset.category = layer.category;
                
                label.appendChild(checkbox);
                
                // Add image if available
                if (layer.imageUrl) {
                    const img = document.createElement('img');
                    img.src = layer.imageUrl;
                    img.alt = layer.title;
                    img.className = 'layer-image';
                    label.appendChild(img);
                }
                
                label.appendChild(document.createTextNode(` ${layer.title}`));
                
                // Get or create section for this category
                let section = container.querySelector(`[data-section="${layer.category}"]`);
                if (!section) {
                    section = document.createElement('div');
                    section.className = 'layer-section';
                    section.dataset.section = layer.category;
                    
                    const title = document.createElement('h3');
                    title.className = 'layer-section-title';
                    if (layer.category === 'extent') {
                        title.textContent = 'Zasięgi poglądowe (widoczne po oddaleniu)';
                    } else {
                        title.textContent = 'Arkusze z linkami do konkretnych plików (widoczne po przybliżeniu)';
                    }
                    section.appendChild(title);
                    container.appendChild(section);
                }
                
                section.appendChild(label);
            });
            
            // Update visibility based on current zoom level after sections are created
            updateVisibleLayers();
        })
        .catch(error => {
            console.error('Error loading layers:', error);
            document.getElementById('layersContainer').innerHTML = `<p class="error-message">Wystąpił błąd przy ładowaniu warstw: ${error.message}</p>`;
        });
}

function setupLayerListeners() {
    const layersContainer = document.getElementById('layersContainer');
    layersContainer.addEventListener('change', (e) => {
        if (e.target.classList.contains('layer-checkbox')) {
            updateWmsLayer();
        }
    });
    
    // Listen for zoom changes to show/hide layers based on zoom level
    map.on('zoomend', updateVisibleLayers);
}
