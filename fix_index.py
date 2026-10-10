import re

with open("pages/index.html", "r") as f:
    content = f.read()

# 1. Strip Emojis
content = content.replace("&#128065;", "[SHOW]")
content = content.replace("&#128203;", "[COPY]")
content = content.replace("&#128274;", "[HIDE]")
content = content.replace("&#10003;", "[OK]")
content = content.replace("&#9888;", "[WARN]")
content = content.replace("&#8505;", "[INFO]")

# 2. Update Cluster Common Key HTML
cluster_html_old = """                            <div class="relative">
                                <input type="text" id="setting-cluster-secret" placeholder="blast-cluster-mesh-secret-key" class="font-fira text-xs bg-slate-900 border border-amber-500/50 text-amber-200 pl-3 pr-24 py-2 rounded w-full focus:outline-none focus:border-amber-400 font-bold">
                                <div class="absolute right-1 top-1 flex items-center gap-1">
                                    <button type="button" onclick="generateClusterKey()" class="px-1.5 py-0.5 bg-amber-500/20 text-amber-300 text-[10px] font-mono rounded hover:bg-amber-500/30" title="Generate random key">GEN</button>
                                    <button type="button" onclick="toggleFieldVis('setting-cluster-secret', this)" class="p-1 text-slate-400 hover:text-amber-300 text-xs" title="Toggle visibility">[SHOW]</button>
                                    <button type="button" onclick="copyFieldValue('setting-cluster-secret')" class="p-1 text-slate-400 hover:text-amber-300 text-xs" title="Copy key">[COPY]</button>
                                </div>
                            </div>"""
cluster_html_new = """                            <div id="cluster-keys-container" class="space-y-2">
                                <!-- Dynamic fields injected here -->
                            </div>
                            <div class="pt-2">
                                <button type="button" onclick="addClusterKeyField()" class="font-chakra text-[10px] bg-amber-500/20 text-amber-300 px-2 py-1 rounded border border-amber-500/40 hover:bg-amber-500/30">+ ADD COMMON KEY</button>
                            </div>"""
content = content.replace(cluster_html_old, cluster_html_new)

# 3. Update toggleFieldVis
content = content.replace("btn.innerHTML = '[HIDE]';", "btn.innerText = '[HIDE]';")
content = content.replace("btn.innerHTML = '[SHOW]';", "btn.innerText = '[SHOW]';")

# 4. Add addClusterKeyField function and delete generateClusterKey
js_funcs = """        function addClusterKeyField(val = '') {
            const container = document.getElementById('cluster-keys-container');
            const id = 'cluster-key-' + Date.now() + Math.floor(Math.random() * 1000);
            const div = document.createElement('div');
            div.className = 'relative flex gap-2 items-center';
            div.innerHTML = `
                <div class="relative flex-1">
                    <input type="password" id="${id}" value="${val}" placeholder="https://your-blast-server.onrender.com" class="cluster-secret-input font-fira text-xs bg-slate-900 border border-amber-500/50 text-amber-200 pl-3 pr-24 py-2 rounded w-full focus:outline-none focus:border-amber-400 font-bold">
                    <div class="absolute right-1 top-1 flex items-center gap-1">
                        <button type="button" onclick="toggleFieldVis('${id}', this)" class="p-1 text-slate-400 hover:text-amber-300 text-xs" title="Toggle visibility">[SHOW]</button>
                        <button type="button" onclick="copyFieldValue('${id}')" class="p-1 text-slate-400 hover:text-amber-300 text-xs" title="Copy key">[COPY]</button>
                    </div>
                </div>
                <button type="button" onclick="this.parentElement.remove()" class="text-rose-400 hover:text-rose-300 text-lg">&times;</button>
            `;
            container.appendChild(div);
        }
"""
content = re.sub(r'        function generateClusterKey\(\) \{.*?\n        \}', js_funcs, content, flags=re.DOTALL)

# 5. Update loadSettingsFromGateway
content = content.replace("document.getElementById('setting-cluster-secret').value = data.blast_cluster_secret || '';", """
                const container = document.getElementById('cluster-keys-container');
                container.innerHTML = '';
                if (data.blast_cluster_secrets && data.blast_cluster_secrets.length > 0) {
                    data.blast_cluster_secrets.forEach(k => addClusterKeyField(k));
                } else {
                    addClusterKeyField('blast-cluster-mesh-secret-key');
                }""")

# 6. Update saveSettingsToGateway
content = content.replace("blast_cluster_secret: document.getElementById('setting-cluster-secret').value.trim(),", 
"""blast_cluster_secrets: Array.from(document.querySelectorAll('.cluster-secret-input')).map(el => el.value.trim()).filter(v => v),""")

content = content.replace("if (!payload.blast_cluster_secret) {", "if (!payload.blast_cluster_secrets || payload.blast_cluster_secrets.length === 0) {")
content = content.replace("'Common Cluster Mesh Secret Key cannot be empty.'", "'At least one Common Cluster Mesh Secret Key must be provided.'")

with open("pages/index.html", "w") as f:
    f.write(content)
