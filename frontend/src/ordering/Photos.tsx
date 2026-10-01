import { useEffect, useRef, useState } from "react";
import { Alert, Field } from "../ui";

export interface MenuPhoto {
  id: string;
  url: string;
  thumbnail_url: string;
  focal_x: number;
  focal_y: number;
}
export interface PhotoDraft {
  key: string;
  id?: string;
  file?: File;
  url: string;
  focal_x: number;
  focal_y: number;
}
export const photoPosition = (photo: { focal_x: number; focal_y: number }) =>
  `${photo.focal_x}% ${photo.focal_y}%`;

export function usePhotos(initial: MenuPhoto[]) {
  const [photos, setPhotos] = useState<PhotoDraft[]>(() =>
    initial.map((p) => ({ ...p, key: p.id })),
  );
  const urls = useRef<string[]>([]);
  useEffect(() => () => urls.current.forEach(URL.revokeObjectURL), []);
  function add(files: File[]) {
    const added = files.map((file) => {
      const url = URL.createObjectURL(file);
      urls.current.push(url);
      return { key: url, url, file, focal_x: 50, focal_y: 50 };
    });
    setPhotos((all) => [...all, ...added]);
  }
  function form(payload: Record<string, unknown>) {
    const data = new FormData();
    const rows = photos.map((photo, i) => {
      const source = photo.file ? { upload: `photo_${i}` } : { id: photo.id };
      if (photo.file) data.append(`photo_${i}`, photo.file);
      return { ...source, focal_x: photo.focal_x, focal_y: photo.focal_y };
    });
    data.append("payload", JSON.stringify({ ...payload, photos: rows }));
    return data;
  }
  return { photos, setPhotos, add, form };
}

export function PhotoEditor({
  state,
}: {
  state: ReturnType<typeof usePhotos>;
}) {
  const { photos, setPhotos } = state;
  const [error, setError] = useState("");
  const [dragged, setDragged] = useState<string | null>(null);
  function move(from: number, to: number) {
    setPhotos((all) => {
      const next = [...all];
      const [photo] = next.splice(from, 1);
      next.splice(to, 0, photo);
      return next;
    });
  }
  return (
    <section className="photo-editor" aria-label="餐點照片">
      <strong>餐點照片（選填）</strong>
      <p className="muted">第一張是列表主圖。拖曳或用箭頭排序，儲存後生效。</p>
      <Field label="新增照片（可多選）">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (photos.length + files.length > 12) {
              setError("每道菜最多 12 張照片。");
              return;
            }
            if (files.some((f) => f.size > 10 * 1024 * 1024)) {
              setError("每張照片最多 10 MB。");
              return;
            }
            setError("");
            state.add(files);
          }}
        />
      </Field>
      <small className="muted">
        JPEG、PNG、WebP，每張最多 10 MB、2400 萬像素；系統會自動縮圖。
      </small>
      <Alert message={error} />
      <ol className="photo-list">
        {photos.map((photo, i) => (
          <li
            key={photo.key}
            className="photo-row"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const from = photos.findIndex((p) => p.key === dragged);
              if (from >= 0 && from !== i) move(from, i);
              setDragged(null);
            }}
          >
            <img
              src={photo.url}
              alt={`第 ${i + 1} 張照片預覽`}
              className="menu-photo-thumb"
              style={{ objectPosition: photoPosition(photo) }}
              draggable
              onDragStart={() => setDragged(photo.key)}
              onDragEnd={() => setDragged(null)}
            />
            <div className="photo-controls">
              <strong>{i === 0 ? "列表主圖" : `照片 ${i + 1}`}</strong>
              <div className="actions">
                <button
                  type="button"
                  aria-label={`照片 ${i + 1} 上移`}
                  disabled={i === 0}
                  onClick={() => move(i, i - 1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`照片 ${i + 1} 下移`}
                  disabled={i === photos.length - 1}
                  onClick={() => move(i, i + 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="danger"
                  onClick={() =>
                    setPhotos((all) => all.filter((p) => p.key !== photo.key))
                  }
                >
                  移除
                </button>
              </div>
              {i === 0 && (
                <details>
                  <summary>調整縮圖位置</summary>
                  {(["focal_x", "focal_y"] as const).map((axis) => (
                    <Field
                      key={axis}
                      label={axis === "focal_x" ? "左右位置" : "上下位置"}
                    >
                      <input
                        type="range"
                        min={0}
                        max={100}
                        value={photo[axis]}
                        onChange={(e) =>
                          setPhotos((all) =>
                            all.map((p) =>
                              p.key === photo.key
                                ? { ...p, [axis]: Number(e.target.value) }
                                : p,
                            ),
                          )
                        }
                      />
                    </Field>
                  ))}
                  <small className="muted">
                    預覽與列表裁切相同；詳情顯示完整照片。
                  </small>
                </details>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
