#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.U2D.Sprites;
using UnityEngine;

namespace Game.UI
{
   // arttool ui bake 가 낸 ui_manifest.json 을 읽어 아틀라스 임포터 설정과 9-slice border 를 넣는다.
   // 사람이 Sprite Editor 를 열 일이 없다. 설정이 전부 코드와 JSON 에 있다.
   public class UiImportSettings : AssetPostprocessor
   {
      const string ManifestName = "ui_manifest.json";

      // 임포트 설정과 SpriteRect 를 한자리에서 넣는다. Postprocess 에서 SaveAndReimport 를 부르면
      // 텍스처마다 임포트가 두 번 돌고 병렬 임포트에서 서로 밟는다.
      void OnPreprocessTexture()
      {
         UiManifest manifest = LoadManifest(assetPath);
         if (manifest == null)
         {
            return;
         }

         TextureImporter importer = (TextureImporter)assetImporter;
         importer.textureType = TextureImporterType.Sprite;
         importer.spriteImportMode = SpriteImportMode.Multiple;
         importer.filterMode = FilterMode.Point;
         importer.mipmapEnabled = false;
         importer.textureCompression = TextureImporterCompression.Uncompressed;
         importer.spritePixelsPerUnit = manifest.ppu;
         importer.alphaIsTransparency = true;
         importer.wrapMode = TextureWrapMode.Clamp;

         ApplyRects(manifest);
      }

      void ApplyRects(UiManifest manifest)
      {
         int height = manifest.atlas_size != null && manifest.atlas_size.Length == 2 ? manifest.atlas_size[1] : 0;
         if (height <= 0)
         {
            Debug.LogWarning($"매니페스트에 atlas_size 가 없어 SpriteRect 를 못 넣는다 : {assetPath}");
            return;
         }

         var factories = new SpriteDataProviderFactories();
         factories.Init();
         ISpriteEditorDataProvider provider = factories.GetSpriteEditorDataProviderFromObject(assetImporter);
         if (provider == null)
         {
            return;
         }

         provider.InitSpriteEditorDataProvider();
         provider.SetSpriteRects(BuildRects(manifest, height, provider.GetSpriteRects()));
         provider.Apply();
      }

      // 매니페스트는 아틀라스 PNG 와 같은 폴더에 있어야 한다. 없으면 이 임포터는 아무것도 안 한다.
      static UiManifest LoadManifest(string texturePath)
      {
         string folder = Path.GetDirectoryName(texturePath);
         if (string.IsNullOrEmpty(folder))
         {
            return null;
         }

         string manifestPath = Path.Combine(folder, ManifestName).Replace('\\', '/');
         if (!File.Exists(manifestPath))
         {
            return null;
         }

         UiManifest manifest = JsonUtility.FromJson<UiManifest>(File.ReadAllText(manifestPath));
         if (manifest == null || manifest.atlas != Path.GetFileName(texturePath))
         {
            return null;
         }
         return manifest;
      }

      static SpriteRect[] BuildRects(UiManifest manifest, int textureHeight, SpriteRect[] existing)
      {
         var made = new List<SpriteRect>();
         foreach (UiFrame frame in manifest.frames)
         {
            SpriteRect rect = MakeRect(frame.name, frame.rect, textureHeight, existing);
            rect.border = new Vector4(frame.border[0], frame.border[1], frame.border[2], frame.border[3]);
            made.Add(rect);
         }

         foreach (UiIcon icon in manifest.icons)
         {
            made.Add(MakeRect(icon.name, icon.rect, textureHeight, existing));
         }
         return made.ToArray();
      }

      // 매니페스트 rect 는 왼쪽 위 기준이고 Unity 는 왼쪽 아래 기준이라 y 를 뒤집는다.
      static SpriteRect MakeRect(string name, int[] box, int textureHeight, SpriteRect[] existing)
      {
         float width = box[2] - box[0];
         float height = box[3] - box[1];
         return new SpriteRect
         {
            name = name,
            spriteID = FindId(name, existing),
            rect = new Rect(box[0], textureHeight - box[3], width, height),
            alignment = SpriteAlignment.Center,
            pivot = new Vector2(0.5f, 0.5f)
         };
      }

      // 이름이 같으면 옛 GUID 를 그대로 쓴다. 안 그러면 씬에 걸린 참조가 끊긴다.
      static GUID FindId(string name, SpriteRect[] existing)
      {
         if (existing == null)
         {
            return GUID.Generate();
         }

         foreach (SpriteRect rect in existing)
         {
            if (rect.name == name)
            {
               return rect.spriteID;
            }
         }
         return GUID.Generate();
      }
   }
}
#endif
