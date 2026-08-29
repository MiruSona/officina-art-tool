#if UNITY_EDITOR
using System;
using System.IO;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;

namespace Game.UI
{
   // arttool ui bake 가 낸 font_bake.json 을 읽고, 거기 적힌 charset.txt 로 TMP 폰트 에셋을 굽는다.
   // 경로는 font_bake.json 한 곳에서만 정한다. 이 파일에는 기본 자리만 있다.
   // 픽셀 폰트라 Raster Hinted + Bitmap 셰이더 + Point 필터로 굽는다. SDF 로 구우면 뭉갠다.
   public static class TmpFontBaker
   {
      const int AtlasPadding = 4;
      const string SettingsPath = "Assets/UI/font_bake.json";

      [MenuItem("Tools/ArtTool/Bake UI Font")]
      public static void BakeFromMenu()
      {
         FontBakeSettings settings = LoadSettings(SettingsPath);
         if (settings == null)
         {
            Debug.LogError($"폰트 굽기 설정이 없다 : {SettingsPath}");
            return;
         }
         Bake(settings);
      }

      // 배치 모드용. Unity -batchmode -executeMethod Game.UI.TmpFontBaker.BakeFromArgs 로 부른다.
      public static void BakeFromArgs()
      {
         string path = ArgValue("-fontSettings", SettingsPath);
         FontBakeSettings settings = LoadSettings(path);
         if (settings == null)
         {
            throw new InvalidOperationException($"폰트 굽기 설정이 없다 : {path}");
         }
         Bake(settings);
      }

      public static TMP_FontAsset Bake(FontBakeSettings settings)
      {
         Font source = AssetDatabase.LoadAssetAtPath<Font>(settings.sourceFont);
         if (source == null)
         {
            throw new InvalidOperationException($"원본 폰트를 못 찾았다 : {settings.sourceFont}");
         }

         string charset = ReadCharset(settings.charsetPath);
         if (charset.Length == 0)
         {
            throw new InvalidOperationException($"글자가 0개다 : {settings.charsetPath}");
         }

         // Dynamic 으로 만들어야 글자를 넣을 수 있다. Static 인 에셋은 TryAddCharacters 를 거절한다.
         TMP_FontAsset asset = TMP_FontAsset.CreateFontAsset(
            source,
            settings.nativePx,
            AtlasPadding,
            GlyphRenderMode.RASTER_HINTED,
            settings.atlasMax,
            settings.atlasMax,
            AtlasPopulationMode.Dynamic,
            false);

         if (asset == null)
         {
            throw new InvalidOperationException("TMP 폰트 에셋을 못 만들었다");
         }

         bool added = asset.TryAddCharacters(charset, out string missing);
         int missingCount = string.IsNullOrEmpty(missing) ? 0 : missing.Length;
         Debug.Log($"글자 {charset.Length}자 중 {charset.Length - missingCount}자를 넣었다 (못 넣은 것 {missingCount}자)");
         if (!added && missingCount == charset.Length)
         {
            throw new InvalidOperationException("글자를 하나도 못 넣었다. 원본 폰트와 charset 을 본다");
         }
         if (missingCount > 0)
         {
            Debug.LogWarning($"원본 폰트에 없는 글자 {missingCount}자를 건너뛰었다");
         }

         // 다 넣은 뒤에 잠근다. 런타임에 글자를 더 굽지 않아 결과가 늘 같다.
         asset.atlasPopulationMode = AtlasPopulationMode.Static;
         MakeCrisp(asset);
         Save(asset, settings.outputPath);
         return asset;
      }

      // 아틀라스를 그냥 텍스처로 찍는다. Bilinear 이면 픽셀이 흐려진다.
      static void MakeCrisp(TMP_FontAsset asset)
      {
         if (asset.atlasTexture != null)
         {
            asset.atlasTexture.filterMode = FilterMode.Point;
         }

         Shader bitmap = Shader.Find("TextMeshPro/Bitmap");
         if (bitmap == null)
         {
            Debug.LogWarning("TextMeshPro/Bitmap 셰이더를 못 찾았다. 기본 셰이더로 둔다");
            return;
         }
         asset.material.shader = bitmap;
      }

      static void Save(TMP_FontAsset asset, string outputPath)
      {
         MakeFolders(Path.GetDirectoryName(outputPath));

         AssetDatabase.CreateAsset(asset, outputPath);
         asset.material.name = asset.name + " Material";
         AssetDatabase.AddObjectToAsset(asset.material, asset);
         if (asset.atlasTexture != null)
         {
            asset.atlasTexture.name = asset.name + " Atlas";
            AssetDatabase.AddObjectToAsset(asset.atlasTexture, asset);
         }

         AssetDatabase.SaveAssets();
         AssetDatabase.Refresh();
         Debug.Log($"폰트 에셋을 구웠다 : {outputPath}");
      }

      // Directory.CreateDirectory 로 만든 폴더는 AssetDatabase 가 모른다. CreateFolder 로 한 칸씩 만든다.
      static void MakeFolders(string folder)
      {
         if (string.IsNullOrEmpty(folder) || AssetDatabase.IsValidFolder(folder))
         {
            return;
         }

         string[] parts = folder.Replace('\\', '/').Split('/');
         string grown = parts[0];
         for (int i = 1; i < parts.Length; i++)
         {
            string next = grown + "/" + parts[i];
            if (!AssetDatabase.IsValidFolder(next))
            {
               AssetDatabase.CreateFolder(grown, parts[i]);
            }
            grown = next;
         }
      }

      static string ReadCharset(string path)
      {
         if (!File.Exists(path))
         {
            throw new InvalidOperationException($"charset.txt 가 없다 : {path}");
         }
         return File.ReadAllText(path).Replace("\r", string.Empty).Replace("\n", string.Empty);
      }

      static FontBakeSettings LoadSettings(string path)
      {
         if (!File.Exists(path))
         {
            return null;
         }
         return JsonUtility.FromJson<FontBakeSettings>(File.ReadAllText(path));
      }

      static string ArgValue(string key, string fallback)
      {
         string[] args = Environment.GetCommandLineArgs();
         for (int i = 0; i < args.Length - 1; i++)
         {
            if (args[i] == key)
            {
               return args[i + 1];
            }
         }
         return fallback;
      }
   }
}
#endif
