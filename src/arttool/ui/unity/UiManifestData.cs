#if UNITY_EDITOR
using System;

namespace Game.UI
{
   // 칸 이름이 밑줄인 것은 JsonUtility 가 JSON 칸 이름을 그대로 맞춰야 읽기 때문이다.
   // 이름 바꾸기 기능이 없어서 C# 명명 규칙보다 JSON 과의 1:1 을 골랐다.
   [Serializable]
   public class UiFrame
   {
      public string name;
      public int[] rect;
      public int[] border;
      public int[] min_size;
      public int[] content_padding;
      public string state;
      public string group;
   }

   [Serializable]
   public class UiIcon
   {
      public string name;
      public int[] rect;
      public int size;
      public string family;
      public int[] hotspot;
   }

   [Serializable]
   public class UiManifest
   {
      public int version;
      public string profile;
      public int ppu;
      public int[] reference;
      public float slice_scale;
      public string atlas;
      public int[] atlas_size;
      public UiFrame[] frames;
      public UiIcon[] icons;
   }

   [Serializable]
   public class FontBakeSettings
   {
      public string sourceFont;
      public string charsetPath;
      public string outputPath;
      public int nativePx;
      public int atlasMax;
   }
}
#endif
