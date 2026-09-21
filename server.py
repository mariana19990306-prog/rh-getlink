from flask import Flask, request, jsonify, send_from_directory
import yt_dlp, os, glob, threading, time, re

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.join(BASE, "downloads")
os.makedirs(DL, exist_ok=True)

progress_data = {}
progress_lock = threading.Lock()

def auto_clean():
    while True:
        time.sleep(60)
        try:
            for f in glob.glob(os.path.join(DL, "*.mp4")):
                if time.time() - os.path.getmtime(f) > 60:
                    try:
                        os.remove(f)
                        print(f"AUTO DELETE: {os.path.basename(f)} - PC gak jebol")
                    except: pass
            now = time.time()
            with progress_lock:
                to_del = [k for k,v in progress_data.items() if now - v.get('start_time', now) > 1800]
                for k in to_del:
                    del progress_data[k]
        except Exception as e:
            print("clean error", e)

threading.Thread(target=auto_clean, daemon=True).start()

@app.after_request
def after_request(r):
    r.headers.add('Access-Control-Allow-Origin','*')
    r.headers.add('Access-Control-Allow-Headers','*')
    r.headers.add('Access-Control-Allow-Methods','*')
    return r

@app.route('/')
def home():
    return "RH-Getlink Server - Paste -> all reso -> click -> PC download -> APK % ngikut PC - ORIGINAL 1080p60"

@app.route('/files/<path:f>')
def files(f):
    # JANGAN auto delete di sini, biar gak gagal pas lagi di-download HP
    # Hapus nya nanti lewat /api/yt/delete setelah HP selesai (3 detik)
    return send_from_directory(DL, f)

@app.route('/api/yt/delete')
def api_yt_delete():
    task_id = request.args.get('task_id','')
    file = request.args.get('file','')
    # hapus 3 detik setelah HP selesai, biar pasti kehapus walau file lagi dibuka
    def do_delete():
        time.sleep(3)
        try:
            if file:
                p = os.path.join(DL, os.path.basename(file))
                for _ in range(3):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                            print(f"DELETE 3 detik via file: {file} - PC bersih")
                            break
                        except:
                            time.sleep(1)
            if task_id:
                with progress_lock:
                    data = progress_data.get(task_id, {})
                    furl = data.get('filename','')
                    targets = []
                    if furl:
                        targets.append(os.path.join(DL, furl))
                    # cari semua file dengan task_id exact
                    targets.extend(glob.glob(os.path.join(DL, f"{task_id}.*")))
                    # backup: cari dengan vid prefix
                    vid_prefix = task_id.split('_')[0] if '_' in task_id else task_id
                    targets.extend(glob.glob(os.path.join(DL, f"{vid_prefix}*.mp4")))
                    targets = list(set(targets))
                    for fp in targets:
                        for _ in range(3):
                            if os.path.exists(fp):
                                try:
                                    os.remove(fp)
                                    print(f"DELETE 3 detik: {os.path.basename(fp)} - PC bersih, task {task_id}")
                                    break
                                except Exception as e:
                                    print(f"retry delete {fp}: {e}")
                                    time.sleep(1)
                    if task_id in progress_data:
                        del progress_data[task_id]
        except Exception as e:
            print(f"delete error {e}")
    threading.Thread(target=do_delete, daemon=True).start()
    return jsonify({"deleted": True, "msg": "Akan terhapus 3 detik setelah selesai di HP - PC bersih"})

def make_task_id(vid, height, fps):
    return f"{vid}_{height}p{fps if fps else ''}"

def get_all_formats_fast(url):
    # FIX FULL ORIGINAL: pilih AVC MP4 mentah paling gede, bukan VP9 yang ke-compress
    # SnapTube 186MB itu AVC 1080p60 MP4 + M4A, bukan VP9 176MB
    ydl_opts = {'quiet':True,'noplaylist':True,'nocheckcertificate':True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        vid = info.get('id','video')
        title = info.get('title','video')
        formats = info.get('formats',[])
        
        # kumpulin per resolusi semua format
        reso_map = {} # key -> list of formats
        for f in formats:
            h = f.get('height')
            if not h or h < 144:
                continue
            fps = int(f.get('fps') or 0)
            vcodec = f.get('vcodec') or ''
            if vcodec == 'none' or not vcodec:
                continue
            key = (h, fps)
            if key not in reso_map:
                reso_map[key] = []
            reso_map[key].append(f)
        
        # untuk tiap resolusi, pilih yang paling ORIGINAL (AVC MP4 + filesize terbesar)
        best_map = {}
        for key, flist in reso_map.items():
            # sort: prefer AVC/H264 + MP4 + filesize terbesar + tbr terbesar
            def score(fmt):
                vcodec = (fmt.get('vcodec') or '').lower()
                ext = (fmt.get('ext') or '').lower()
                is_avc = 1 if 'avc' in vcodec or 'h264' in vcodec else 0
                is_mp4 = 1 if ext == 'mp4' else 0
                # SnapTube pakai AVC MP4, bukan VP9 WebM
                size = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                tbr = fmt.get('tbr') or 0
                # bobot: AVC + MP4 paling tinggi, baru size
                return (is_avc*1000000000 + is_mp4*100000000 + size*10 + tbr*1000)
            best = sorted(flist, key=score, reverse=True)[0]
            best_map[key] = best
        
        sorted_reso = sorted(best_map.items(), key=lambda x: (x[0][0], x[0][1]))
        
        result_formats = []
        for (h,fps), fmt in sorted_reso:
            if h < 144:
                continue
            has_audio = fmt.get('acodec') != 'none' and fmt.get('acodec')
            label = f"{h}p"
            if fps >= 48:
                label = f"{h}p{fps}"
            res_str = f"{h}p{fps}fps" if fps else f"{h}p"
            
            task_id = make_task_id(vid, h, fps)
            download_api_url = f"/api/yt/download?url={url}&id={vid}&height={h}&fps={fps}&format_id={fmt.get('format_id','')}"
            
            result_formats.append({
                "format_id": fmt.get('format_id'),
                "height": h,
                "fps": fps,
                "label": label,
                "res": res_str,
                "ext": fmt.get('ext','mp4'),
                "has_audio": bool(has_audio),
                "needs_merge": not has_audio and h >= 720,
                "tbr": fmt.get('tbr'),
                "filesize": fmt.get('filesize') or fmt.get('filesize_approx'),
                "vcodec": fmt.get('vcodec'),
                "acodec": fmt.get('acodec'),
                "download_url": download_api_url,
                "task_id": task_id
            })
        
        if not result_formats:
            result_formats = [{
                "format_id": "best",
                "height": 720,
                "fps": 30,
                "label": "720p",
                "res": "720p",
                "ext": "mp4",
                "has_audio": True,
                "needs_merge": False,
                "download_url": f"/api/yt/download?url={url}&id={vid}&height=720&fps=30&format_id=best",
                "task_id": make_task_id(vid,720,30)
            }]
        
        return {"id": vid, "title": title, "formats": result_formats}

def progress_hook_factory(task_id):
    def hook(d):
        with progress_lock:
            if task_id not in progress_data:
                progress_data[task_id] = {}
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                percent = 0
                if total and downloaded:
                    percent = downloaded / total * 100
                p_str = d.get('_percent_str','').strip()
                if p_str:
                    try:
                        percent = float(p_str.replace('%','').strip())
                    except:
                        pass
                speed = d.get('speed')
                eta = d.get('eta')
                filename = d.get('filename','')
                is_audio = '.m4a' in filename or 'audio' in filename.lower()
                
                prog = progress_data[task_id]
                if is_audio:
                    prog['audio_percent'] = percent
                else:
                    prog['video_percent'] = percent
                
                v = prog.get('video_percent', 0)
                a = prog.get('audio_percent', 0)
                if prog.get('needs_merge'):
                    combined = (v*0.9 + a*0.1) if a else v*0.9
                    if combined > 90:
                        combined = 90
                    percent = combined
                else:
                    percent = v or percent
                
                prog.update({
                    'status': 'downloading',
                    'percent': round(percent,1),
                    'speed': speed,
                    'eta': eta,
                    'filename': os.path.basename(filename)
                })
            elif d['status'] == 'finished':
                prog = progress_data[task_id]
                prog.update({'status': 'merging', 'percent': 95})
            elif d['status'] == 'error':
                progress_data[task_id].update({'status': 'error', 'percent': 0})
    return hook

def download_task(url, vid, height, fps, format_id, task_id, host_url):
    try:
        with progress_lock:
            progress_data[task_id].update({'status':'downloading','percent':0,'start_time':time.time()})
        
        exact_pattern = os.path.join(DL, f"{task_id}.*")
        exact_existing = glob.glob(exact_pattern)
        if exact_existing:
            fname = os.path.basename(exact_existing[0])
            if os.path.getsize(exact_existing[0]) > 10*1024*1024:
                file_url = f"{host_url.rstrip('/')}/files/{fname}"
                with progress_lock:
                    progress_data[task_id].update({
                        'status':'ready',
                        'percent':100,
                        'file_url': file_url,
                        'filename': fname
                    })
                return
        
        h = int(height)
        f = int(fps) if str(fps).isdigit() else 0
        
        if format_id and format_id != 'best':
            if h >= 1080:
                # FIX FULL ORIGINAL: format_id (299 AVC MP4) + 140 M4A mentah, no re-encode
                fmt_str = f"{format_id}+140/{format_id}+bestaudio[ext=m4a]/bestaudio[ext=m4a]/bestaudio"
            else:
                fmt_str = format_id
            needs_merge = h >= 720
        else:
            if h >= 1080 and f >= 48:
                # KUNCI 1080p60 ORIGINAL 186MB KAYAK SNAP: AVC MP4 + M4A, copy tanpa compress
                fmt_str = f"bestvideo[height={h}][fps={f}][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/bestvideo[height={h}][fps={f}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height={h}][fps={f}]+bestaudio/bestvideo[height={h}][fps>=48][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height={h}][fps>=48]+bestaudio"
                needs_merge = True
            elif h >= 1080:
                fmt_str = f"bestvideo[height={h}][fps<48][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/bestvideo[height={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height={h}]+bestaudio"
                needs_merge = True
            else:
                fmt_str = f"bestvideo[height={h}][ext=mp4]+bestaudio[ext=m4a]/best[height={h}][ext=mp4]/best[height={h}]/best"
                needs_merge = h >= 720
        
        with progress_lock:
            progress_data[task_id]['needs_merge'] = needs_merge
        
        opts = {
            'format': fmt_str,
            'format_sort': ['res:1080', 'fps:60', 'vcodec:h264', 'acodec:m4a', 'ext:mp4:m4a', 'size', 'br'],
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(DL, f"{task_id}.%(ext)s"),
            'noplaylist': True,
            'progress_hooks': [progress_hook_factory(task_id)],
            'quiet': False,
            'nocheckcertificate': True,
            # FIX FULL ORIGINAL: jangan re-encode, copy mentah biar bitrate asli gak ke-compress
            'postprocessors': [{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}],
            'postprocessor_args': {
                'Merger': ['-c:v', 'copy', '-c:a', 'copy'],
                'FFmpegVideoRemuxer': ['-c:v', 'copy', '-c:a', 'copy']
            },
        }
        
        print(f"DOWNLOAD TASK {task_id} FORMAT: {fmt_str}")
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        
        final = glob.glob(os.path.join(DL, f"{task_id}.*"))
        if not final:
            final = glob.glob(os.path.join(DL, f"{vid}*.mp4"))
        if final:
            final_sorted = sorted(final, key=lambda x: os.path.getsize(x), reverse=True)
            for cand in final_sorted:
                if cand.endswith('.mp4') or cand.endswith('.mkv'):
                    fname = os.path.basename(cand)
                    file_url = f"{host_url.rstrip('/')}/files/{fname}"
                    with progress_lock:
                        progress_data[task_id].update({
                            'status':'ready',
                            'percent':100,
                            'file_url': file_url,
                            'filename': fname
                        })
                    print(f"DONE {task_id} -> {file_url} SIZE {os.path.getsize(cand)}")
                    return
            fname = os.path.basename(final_sorted[0])
            file_url = f"{host_url.rstrip('/')}/files/{fname}"
            with progress_lock:
                progress_data[task_id].update({
                    'status':'ready',
                    'percent':100,
                    'file_url': file_url,
                    'filename': fname
                })
        else:
            with progress_lock:
                progress_data[task_id].update({'status':'error','percent':0})
    except Exception as e:
        print(f"DOWNLOAD ERROR {task_id}: {e}")
        import traceback; traceback.print_exc()
        with progress_lock:
            if task_id in progress_data:
                progress_data[task_id].update({'status':'error','percent':0,'error':str(e)})

@app.route('/api/yt')
def api_yt():
    try:
        url = request.args.get('url','')
        if not url:
            return jsonify({"original_hd":""}),400
        info = get_all_formats_fast(url)
        host = request.host_url.rstrip('/')
        for f in info['formats']:
            rel = f['download_url']
            f['download_api'] = f"{host}{rel}"
            f['download_url'] = f"{host}{rel}"
        
        orig = ""
        for f in sorted(info['formats'], key=lambda x: (x['height'], x.get('filesize') or 0), reverse=True):
            if f.get('height',0) >= 1080:
                orig = f['download_api']
                break
        if not orig and info['formats']:
            orig = info['formats'][-1]['download_api']
        
        return jsonify({
            "id": info['id'],
            "title": info['title'],
            "original_hd": orig,
            "formats": info['formats'],
            "res": "1080p60fps" if any(x['height']>=1080 and x['fps']>=50 for x in info['formats']) else "1080p",
            "height": max([x['height'] for x in info['formats']], default=720)
        })
    except Exception as e:
        print("YT INFO ERROR:", e)
        import traceback; traceback.print_exc()
        return jsonify({"original_hd":"","error":str(e)}),200

@app.route('/api/yt/download')
def api_yt_download():
    try:
        url = request.args.get('url','')
        vid = request.args.get('id','video')
        height = request.args.get('height','1080')
        fps = request.args.get('fps','60')
        format_id = request.args.get('format_id','')
        if not url:
            return jsonify({"error":"no url"}),400
        
        task_id = make_task_id(vid, int(height), int(fps) if str(fps).isdigit() else 0)
        host = request.host_url.rstrip('/')
        
        with progress_lock:
            if task_id in progress_data and progress_data[task_id].get('status') == 'ready':
                return jsonify({
                    "task_id": task_id,
                    "status": "ready",
                    "percent": 100,
                    "original_hd": progress_data[task_id].get('file_url',''),
                    "file_url": progress_data[task_id].get('file_url','')
                })
            if task_id in progress_data and progress_data[task_id].get('status') in ['downloading','merging','starting']:
                return jsonify({
                    "task_id": task_id,
                    "status": progress_data[task_id].get('status'),
                    "percent": progress_data[task_id].get('percent',0),
                    "original_hd": "",
                    "file_url": ""
                })
            progress_data[task_id] = {
                'status':'starting',
                'percent':0,
                'start_time': time.time(),
                'vid': vid,
                'height': height,
                'fps': fps
            }
        
        threading.Thread(target=download_task, args=(url, vid, height, fps, format_id, task_id, host), daemon=True).start()
        
        return jsonify({
            "task_id": task_id,
            "status": "starting",
            "percent": 0,
            "original_hd": "",
            "message": f"PC mulai download {height}p{fps} ORIGINAL - size gede kayak Snap2B"
        })
    except Exception as e:
        print("DOWNLOAD START ERROR:", e)
        return jsonify({"error":str(e)}),200

@app.route('/api/yt/progress')
def api_yt_progress():
    task_id = request.args.get('task_id','') or request.args.get('id','')
    if not task_id:
        vid = request.args.get('id','')
        height = request.args.get('height','1080')
        fps = request.args.get('fps','60')
        task_id = make_task_id(vid, int(height) if str(height).isdigit() else 1080, int(fps) if str(fps).isdigit() else 0)
    
    with progress_lock:
        data = progress_data.get(task_id, {})
    
    if not data:
        return jsonify({"task_id": task_id, "status": "not_found", "percent": 0})
    
    return jsonify({
        "task_id": task_id,
        "status": data.get('status','unknown'),
        "percent": data.get('percent',0),
        "speed": data.get('speed'),
        "eta": data.get('eta'),
        "video_percent": data.get('video_percent'),
        "audio_percent": data.get('audio_percent'),
        "file_url": data.get('file_url',''),
        "original_hd": data.get('file_url',''),
        "filename": data.get('filename',''),
        "inside_apk": True,
        "progress_from_pc": True
    })

@app.route('/api/youtube')
def api_youtube():
    return api_yt()

@app.route('/api/progress')
def api_progress():
    return api_yt_progress()

def get_fb(url):
    ydl_opts = {'quiet':True,'noplaylist':True,'format':'best','nocheckcertificate':True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return info.get('url') or (info.get('formats', [{}])[-1].get('url') if info.get('formats') else "")

@app.route('/api/fb')
def api_fb():
    try:
        url = request.args.get('url','')
        if not url:
            return jsonify({"original_hd":""}),400
        fb_url = get_fb(url)
        return jsonify({"original_hd": fb_url or ""})
    except Exception as e:
        print("FB ERROR:", e)
        return jsonify({"original_hd":"", "error":str(e)}),200

@app.route('/api/clear')
def clear():
    cnt=0
    for f in glob.glob(os.path.join(DL, "*")):
        try:
            os.remove(f)
            cnt+=1
        except:
            pass
    with progress_lock:
        progress_data.clear()
    return jsonify({"cleared": cnt, "msg": f"{cnt} file & progress dihapus"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    print(f"=== RH-GETLINK ONLINE 24JAM 186MB ORIGINAL - PORT {port} ===")
    app.run(host='0.0.0.0', port=port, threaded=True)
